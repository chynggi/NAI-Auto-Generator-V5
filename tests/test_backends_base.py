"""백엔드 프로토콜 테스트."""

from naiauto.core.api.models import GenerationRequest, GenerationResult
from naiauto.core.backends.base import ImageBackend, backend_supports_credit


class _Fake:
    supports_credit = False

    def generate(self, req: GenerationRequest) -> GenerationResult:
        return GenerationResult(raw_bytes=b"png")


class _Legacy:
    """supports_credit을 선언하지 않는 기존 클라이언트 (NAIClient 모양)."""

    def generate(self, req: GenerationRequest) -> GenerationResult:
        return GenerationResult(raw_bytes=b"png")


def test_fake_satisfies_protocol():
    assert isinstance(_Fake(), ImageBackend)
    assert isinstance(_Legacy(), ImageBackend)


def test_supports_credit_reads_declared_flag():
    assert backend_supports_credit(_Fake()) is False


def test_supports_credit_defaults_true_for_legacy_client():
    """NAIClient는 이 플래그를 선언하지 않는다 — 크레딧을 쓰는 쪽이 기본값이어야 한다."""
    assert backend_supports_credit(_Legacy()) is True


def test_real_nai_client_is_a_backend():
    from naiauto.core.api.client import NAIClient

    # ImageBackend는 메서드만 가진 Protocol이라 issubclass가 쓸 수 있다.
    assert issubclass(NAIClient, ImageBackend)
    assert backend_supports_credit(NAIClient.__new__(NAIClient)) is True
