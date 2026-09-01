"""HuggingFace 태그 데이터 다운로더.

NAIA2.0과 동일한 HuggingFace 저장소에서 태그 데이터를 내려받는다:

    https://huggingface.co/baqu2213/PoemForSmallFThings

사용 예:
    downloader = TagDataDownloader()
    downloader.download_tag_corpus(dest_path)

이 모듈은 NAIA2.0 ``core/runtime_install_manager.py`` 의 다운로드 로직을
간소화하여 V5 환경에 맞춘 것이다. 핵심 차이:
  - V5는 parquet 전량이 아니라 CSV/JSON 요약만 필요하다.
  - UI 진행률 보고는 선택 사항(callback)이다.
  - 블로킹/단일 다운로드 — 복잡한 상태 기계가 없다.
"""

from __future__ import annotations

import logging
import ssl
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HuggingFace 저장소 상수
# ---------------------------------------------------------------------------

HF_REPO_OWNER = "baqu2213"
HF_REPO_NAME = "PoemForSmallFThings"
HF_BASE_URL = f"https://huggingface.co/{HF_REPO_OWNER}/{HF_REPO_NAME}/resolve/main"

#: 태그 코퍼스 ZIP (150개 parquet, ~1.4 GB) — Danbooru 태그 전수.
TAG_ARCHIVE_URL = f"{HF_BASE_URL}/naia_tags.zip"

#: 태그 코퍼스 증분 (버킷 150~174, ~275 MB) — 최신 태그 추가분.
TAG_INCREMENT_URL = f"{HF_BASE_URL}/naia_tags_inc_150_174.zip"

#: 이벤트 코퍼스 (대화형 모드 태그 공기 추천).
CORPUS_ARCHIVE_URL = f"{HF_BASE_URL}/NAIA/naia-tag-events.zip"

#: 태그 콤보 번들 (대화형 태그 추천 엔진).
TAG_COMBO_URL = f"{HF_BASE_URL}/NAIA/naia_tag_combo_v4.ncsb"

#: 데이터셋 빌드 원천 (코퍼스 증분 생성용).
DATASET_SOURCE = "BootsofLagrangian/danbooru-multitier-captions-202606"

# ---------------------------------------------------------------------------
# 다운로드 설정
# ---------------------------------------------------------------------------

DOWNLOAD_TIMEOUT = 60
DOWNLOAD_ATTEMPTS = 5
DOWNLOAD_BACKOFF_CAP = 8

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CONTEXT = ssl.create_default_context()


# ---------------------------------------------------------------------------
# 콜백 타입
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[int, str], None]  # percent(0-100), message


# ---------------------------------------------------------------------------
# 데이터셋
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TagDataSet:
    """태그 데이터셋 하나의 명세 — URL, 대상 경로, 예상 파일 수 등."""

    name: str
    url: str
    expected_ext: str = ".parquet"
    expected_count: int = 0


#: 다운로드 가능한 데이터셋 목록.
DATASETS: dict[str, TagDataSet] = {
    "tag_archive": TagDataSet(
        name="태그 코퍼스",
        url=TAG_ARCHIVE_URL,
        expected_ext=".parquet",
        expected_count=150,
    ),
    "tag_increment": TagDataSet(
        name="최신 태그 데이터",
        url=TAG_INCREMENT_URL,
        expected_ext=".parquet",
    ),
    "corpus_archive": TagDataSet(
        name="이벤트 코퍼스",
        url=CORPUS_ARCHIVE_URL,
        expected_ext=".tgp",
    ),
}


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------


def bundled_tags_dir() -> Path:
    """내장 태그 리소스 디렉터리 (resources/tags/)."""
    return Path(__file__).resolve().parent / "tags"


def bundled_taglist_dir() -> Path:
    """내장 taglist 디렉터리."""
    return bundled_tags_dir() / "taglist"


def bundled_tag_index_dir() -> Path:
    """내장 tag_index 디렉터리."""
    return bundled_tags_dir() / "tag_index"


# ---------------------------------------------------------------------------
# 다운로더
# ---------------------------------------------------------------------------


class TagDataDownloader:
    """HuggingFace에서 태그 데이터를 내려받는다.

    V5에 맞게 단순화:
    - 동시 다운로드 없음 (순차)
    - 진행률 콜백 지원
    - 압축 해제 + 검증까지 자동
    """

    def __init__(self, progress_callback: ProgressCallback | None = None) -> None:
        self._progress = progress_callback or (lambda pct, msg: None)
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def download_archive(
        self,
        dataset: TagDataSet,
        dest_dir: Path,
        *,
        extract: bool = True,
    ) -> Path:
        """데이터셋을 내려받고(압축 해제 선택) 최종 경로를 반환한다.

        Returns:
            extract=True → 압축 푼 디렉터리 경로
            extract=False → 다운로드한 ZIP 파일 경로
        """
        self._cancel = False
        dest_dir.mkdir(parents=True, exist_ok=True)

        zip_name = dataset.url.rstrip("/").rsplit("/", 1)[-1]
        zip_path = dest_dir / zip_name

        self._progress(0, f"{dataset.name} 다운로드 연결 중...")
        self._download_file(dataset.url, zip_path)

        if not extract:
            self._progress(100, f"{dataset.name} 다운로드 완료: {zip_path}")
            return zip_path

        self._progress(90, f"{dataset.name} 압축 해제 중...")
        return self._extract_archive(zip_path, dest_dir, dataset.expected_ext)

    def _download_file(self, url: str, dest: Path) -> None:
        """파일을 내려받는다 (이어받기 지원)."""
        dest.parent.mkdir(parents=True, exist_ok=True)

        downloaded = dest.stat().st_size if dest.exists() else 0
        last_error: Exception | None = None

        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            if self._cancel:
                raise InterruptedError("다운로드가 취소되었습니다.")

            headers = {"User-Agent": "NAI-Auto-Generator-V5/0.1.0"}
            if downloaded > 0:
                headers["Range"] = f"bytes={downloaded}-"

            request = urllib.request.Request(url, headers=headers)
            open_kwargs = {"timeout": DOWNLOAD_TIMEOUT}
            if url.startswith("https://"):
                open_kwargs["context"] = SSL_CONTEXT

            try:
                with urllib.request.urlopen(request, **open_kwargs) as resp:
                    can_resume = (
                        downloaded > 0
                        and resp.status == 206
                        and self._range_matches(resp, downloaded)
                    )
                    if downloaded > 0 and not can_resume:
                        downloaded = 0
                        dest.unlink(missing_ok=True)

                    mode = "ab" if can_resume else "wb"
                    downloaded = self._stream_to_file(resp, dest, mode, downloaded)
                last_error = None
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 416 and downloaded > 0:
                    last_error = None
                    break
                raise
            except Exception as exc:
                last_error = exc
                downloaded = dest.stat().st_size if dest.exists() else 0
                if attempt >= DOWNLOAD_ATTEMPTS:
                    break
                import time

                backoff = min(DOWNLOAD_BACKOFF_CAP, 2 ** (attempt - 1))
                self._progress(0, f"{dest.name} 재시도 {attempt}/{DOWNLOAD_ATTEMPTS} ({backoff}s)...")
                time.sleep(backoff)

        if last_error is not None:
            raise last_error

    def _stream_to_file(
        self,
        response: urllib.request._UrlopenRef,
        dest: Path,
        mode: str,
        downloaded: int,
    ) -> int:
        """응답 본문을 파일에 기록한다."""
        total_size = downloaded + int(response.headers.get("content-length", 0) or 0)
        with dest.open(mode) as out:
            while True:
                if self._cancel:
                    raise InterruptedError("다운로드가 취소되었습니다.")
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if total_size:
                    pct = min(85, 10 + int((downloaded * 75) / total_size))
                    mb = round(downloaded / (1024 * 1024), 1)
                    total_mb = round(total_size / (1024 * 1024), 1)
                    self._progress(pct, f"다운로드 중... {pct}% ({mb}/{total_mb} MB)")
        return downloaded

    def _extract_archive(self, zip_path: Path, dest_dir: Path, ext: str) -> Path:
        """ZIP에서 특정 확장자만 추출한다."""
        extracted = 0
        with zipfile.ZipFile(zip_path, "r") as archive:
            members = [info for info in archive.infolist() if info.filename.endswith(ext)]
            for index, info in enumerate(members, 1):
                if self._cancel:
                    raise InterruptedError("압축 해제가 취소되었습니다.")
                filename = Path(info.filename).name
                target = dest_dir / filename
                with archive.open(info) as src, target.open("wb") as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
                extracted += 1
                pct = min(99, 90 + int((index * 9) / len(members)))
                self._progress(pct, f"압축 해제 중... {index}/{len(members)}")
        self._progress(100, f"완료: {extracted}개 파일 → {dest_dir}")
        return dest_dir

    @staticmethod
    def _range_matches(response: urllib.request._UrlopenRef, expected_start: int) -> bool:
        """Content-Range 헤더가 기대한 시작 지점과 일치하는가."""
        raw = str(response.headers.get("content-range", "") or "").strip()
        if not raw.lower().startswith("bytes"):
            return False
        try:
            span = raw.split(None, 1)[1].split("/", 1)[0]
            return int(span.split("-", 1)[0]) == expected_start
        except (IndexError, ValueError):
            return False

    # ------------------------------------------------------------------
    # 단축 메서드
    # ------------------------------------------------------------------

    def download_all_parquet(self, dest_dir: Path) -> list[Path]:
        """모든 태그 코퍼스(parquet)를 내려받는다."""
        results: list[Path] = []
        for key in ("tag_archive", "tag_increment"):
            ds = DATASETS.get(key)
            if ds:
                self.download_archive(ds, dest_dir)
                results.append(dest_dir)
        return results


# ---------------------------------------------------------------------------
# 데이터 파일 경로 조회 함수
# ---------------------------------------------------------------------------


def taglist_paths() -> dict[str, Path]:
    """taglist/*.json 파일 경로를 반환한다."""
    base = bundled_taglist_dir()
    paths: dict[str, Path] = {}
    if base.is_dir():
        for f in base.glob("*.json"):
            paths[f.stem] = f
    return paths


def tag_index_paths() -> dict[str, Path]:
    """tag_index/*.json 파일 경로를 반환한다."""
    base = bundled_tag_index_dir()
    paths: dict[str, Path] = {}
    if base.is_dir():
        for f in base.glob("*.json"):
            paths[f.stem] = f
    return paths


__all__ = [
    "CORPUS_ARCHIVE_URL",
    "DATASETS",
    "DATASET_SOURCE",
    "HF_BASE_URL",
    "HF_REPO_NAME",
    "HF_REPO_OWNER",
    "TAG_ARCHIVE_URL",
    "TAG_COMBO_URL",
    "TAG_INCREMENT_URL",
    "TagDataDownloader",
    "TagDataSet",
    "bundled_tag_index_dir",
    "bundled_taglist_dir",
    "tag_index_paths",
    "taglist_paths",
]
