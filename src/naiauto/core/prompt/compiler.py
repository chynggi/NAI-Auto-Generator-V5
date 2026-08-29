"""프롬프트 컴파일러 오케스트레이션.

자연어 → NovelAI V5 프롬프트 컴파일 파이프라인의 최상위 조율자:
parser(LLM 구조화) → resolver(태그 검증) → positions/relationship(정규화) →
formatter(문자열 조립)를 순서대로 묶어 최종 ``CompiledPrompt``를 만든다.

- ``compile``: 새 프롬프트 생성 (모드: tag/hybrid/natural)
- ``modify``: 기존 프롬프트 수정 — wildcard/artist 토큰(``__dynamic__``,
  ``{artist:grp}``)은 제거하지 않고 보존한다 (스펙 §51, §52)
- ``build_compiler``: AppSettings(duck-typed)에서 전체 의존성을 조립

빈 입력이거나 결과에 scene 태그도 캐릭터도 없으면
``CompilerEmptyResultError``를 던진다. Qt 의존성 없음.
"""

from __future__ import annotations

import re
from dataclasses import replace
from types import SimpleNamespace

from naiauto.core.prompt.errors import CompilerEmptyResultError, CompilerError
from naiauto.core.prompt.formatter import PromptFormatter
from naiauto.core.prompt.llm import LLMProvider
from naiauto.core.prompt.parser import PRESERVED_TOKEN_RE, SceneParser
from naiauto.core.prompt.positions import estimate_positions
from naiauto.core.prompt.providers import API_KEY_CREDENTIAL, create_provider
from naiauto.core.prompt.relationship import normalize_relationships
from naiauto.core.prompt.resolver import TagResolver
from naiauto.core.prompt.retriever import TagRetriever
from naiauto.core.prompt.schema import (
    MODE_TAGS,
    CharacterPrompt,
    CompiledPrompt,
    LLMStructuredPrompt,
    RelationshipPrompt,
    ScenePrompt,
    TagRef,
)
from naiauto.core.settings.credentials import load_credential
from naiauto.core.tag_completer import resolve_database_path

__all__ = ["PromptCompiler", "build_compiler"]

#: final prompt에 포함할 TagRef status (verified/inferred).
_OK_STATUSES = ("verified", "inferred")


class PromptCompiler:
    """전체 파이프라인 오케스트레이션 (스펙 §34 인터페이스)."""

    def __init__(
        self,
        provider: LLMProvider,
        resolver: TagResolver,
        formatter: PromptFormatter,
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: float = 120.0,
        use_resolver: bool = True,
        retriever: TagRetriever | None = None,
        server_manager=None,
    ) -> None:
        self._parser = SceneParser(provider, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
        self._resolver = resolver
        self._formatter = formatter
        #: True = resolver로 태그 검증, False = LLM 원문 태그를 전부 verified로
        self.use_resolver = use_resolver
        #: RAG 리트리버 — None 또는 DB 비활성이면 후보 주입 없이 기존 동작.
        self._retriever = retriever
        #: 자동 기동된 llama-server 프로세스 관리자 (close()에서 종료).
        self._server_manager = server_manager

    def compile(self, text: str, *, mode: str = "hybrid") -> CompiledPrompt:
        """자연어 → CompiledPrompt. 빈 입력은 CompilerEmptyResultError."""
        if mode not in MODE_TAGS:
            raise ValueError(f"invalid mode: {mode!r} (expected one of {MODE_TAGS})")
        if not text.strip():
            raise CompilerEmptyResultError("empty input")
        tags, translations = self._retrieve((text,))
        raw = self._parser.parse(
            text,
            candidate_tags=tags,
            translated_text=translations.get(text, ""),
        )
        return self._assemble(raw, mode)

    def modify(self, existing_prompt: str, instruction: str, *, mode: str = "hybrid") -> CompiledPrompt:
        """기존 프롬프트 수정 — wildcard/artist 토큰 보존 (스펙 §51, §52).

        1. 기존 프롬프트에서 보존 토큰(``__dynamic__``/``{...}``)을 추출해
           파서(LLM)에 알린다.
        2. 결과 base_prompt 태그 라인에 없는 보존 토큰은 태그 라인 끝에
           ", "로 이어붙여 컴파일러가 wildcard를 제거하지 않도록 보장한다
           (NL 문단 뒤가 아니라 태그 라인에 붙는다).
        """
        if mode not in MODE_TAGS:
            raise ValueError(f"invalid mode: {mode!r} (expected one of {MODE_TAGS})")
        preserved = tuple(PRESERVED_TOKEN_RE.findall(existing_prompt))
        tags, translations = self._retrieve((existing_prompt, instruction))
        raw = self._parser.parse(
            instruction,
            existing_prompt=existing_prompt,
            preserved=preserved,
            candidate_tags=tags,
            translated_text=translations.get(instruction, ""),
        )
        result = self._assemble(raw, mode)
        # [Minor #5] 보존 토큰 확인은 부분 문자열이 아니라 태그 목록 세그먼트 단위로 —
        # "1girl"이 "1girls"의 부분 문자열로 오인되는 일이 없도록 한다.
        tag_part = result.base_prompt.split("\n\n", 1)[0]
        missing = [
            token for token in preserved if not re.search(rf"(^|,)\s*{re.escape(token)}\s*(,|$)", tag_part)
        ]
        if missing:
            suffix = ", ".join(missing)
            # [review #2] "\n\n" 뒤는 NL 문단 — 보존 토큰은 태그 라인(head)에 스플라이스한다.
            head, sep, tail = result.base_prompt.partition("\n\n")
            head = f"{head}, {suffix}" if head else suffix
            result = replace(result, base_prompt=f"{head}{sep}{tail}")
        return result

    # ------------------------------------------------------------------
    # 내부 조립
    # ------------------------------------------------------------------

    def _retrieve(self, texts: tuple[str, ...]) -> tuple[tuple[str, ...], dict[str, str]]:
        """RAG: 텍스트별 후보 검색 + 빈 결과 텍스트의 선번역.

        - 각 텍스트를 개별 검색하고, 영문 키워드가 없어 결과가 비면
          ``SceneParser.translate``로 선번역 후 재검색한다.
        - 번역 실패(CompilerError)/빈 응답은 조용히 폴백 — 파싱은 원문으로 진행.
        - 리트리버 없음/DB 비활성 → ((), {}) — 후보·번역 없이 기존 동작.
        """
        if self._retriever is None or not self._retriever.is_enabled:
            return (), {}
        seen: set[str] = set()
        tags: list[str] = []
        translations: dict[str, str] = {}
        for text in texts:
            found = self._retriever.search(text)
            if not found and text.strip():
                try:
                    translated = self._parser.translate(text)
                except CompilerError:
                    translated = ""
                if translated:
                    translations[text] = translated
                    found = self._retriever.search(translated)
            for tag in found:
                if tag not in seen:
                    seen.add(tag)
                    tags.append(tag)
        return tuple(tags), translations

    def _assemble(self, raw: LLMStructuredPrompt, mode: str) -> CompiledPrompt:
        """LLM 구조화 출력(LLMStructuredPrompt) → 최종 CompiledPrompt."""
        unresolved: list[str] = []

        # 1. scene 태그 해석 — verified/inferred만 scene.tags, 나머지는 취합
        scene_refs, scene_unresolved = self._resolve_tags(raw.scene.tags)
        unresolved.extend(scene_unresolved)

        # 2. 캐릭터 태그 해석 + position_hint → 좌표 추정
        built_chars: list[CharacterPrompt] = []
        for model in raw.characters:
            char_refs, char_unresolved = self._resolve_tags(model.tags)
            unresolved.extend(char_unresolved)
            # [review #1] 캐릭터 negative_tags도 resolver 검증 — 환각 네거티브가
            # merge(CharacterCaption.uc)까지 도달하지 못하게 scene negative와 동일한 경로.
            neg_refs, neg_unresolved = self._resolve_tags(model.negative_tags)
            unresolved.extend(neg_unresolved)
            built_chars.append(
                CharacterPrompt(
                    id=model.id,
                    description=model.description,
                    tags=tuple(char_refs),
                    raw_tags=tuple(model.tags),
                    negative_tags=tuple(ref.tag for ref in neg_refs),
                    pose=model.pose,
                    expression=model.expression,
                    position_hint=model.position_hint,
                    natural_language=model.natural_language,
                )
            )
        characters = list(estimate_positions(tuple(built_chars)))

        # 4. 관계 정규화 + 상호 확장으로 생긴 동일 엔트리 중복 제거
        #    (LLM이 mutual 양방향을 2줄 주면 4개가 나오므로 1개로 — formatter가 상호 쌍 처리)
        char_ids = {c.id for c in characters}
        rels, rel_warnings = normalize_relationships(raw.relationships, char_ids)
        seen: set[tuple[str, str, str, bool]] = set()
        relationships: list[RelationshipPrompt] = []
        for rel in rels:
            key = (rel.source, rel.target, rel.action, rel.mutual)
            if key not in seen:
                seen.add(key)
                relationships.append(rel)

        # 5. negative 해석 — verified/inferred만 (unresolved는 final에서 제외).
        #    [Minor #3] negative의 unresolved도 취합해 사용자에게 알린다.
        neg_refs, neg_unresolved = self._resolve_tags(raw.negative)
        unresolved.extend(neg_unresolved)

        # 6. scene 구조 (subjects는 count 태그용)
        scene = ScenePrompt(
            tags=tuple(scene_refs),
            raw_tags=tuple(raw.scene.tags),
            subjects=tuple(raw.scene.subjects),
            description=raw.scene.description,
            natural_language=raw.scene.natural_language,
            camera=raw.camera,
            composition=raw.composition,
            style=raw.style,
        )

        # 7/8. 문자열 조립 + 캐릭터별 최종 prompt_text (merge 레이어가 사용)
        base, negative = self._formatter.format(
            scene=scene,
            characters=tuple(characters),
            relationships=tuple(relationships),
            negative_tags=tuple(neg_refs),
            mode=mode,
        )
        characters = [
            replace(c, prompt_text=self._formatter.character_prompt_text(c, mode)) for c in characters
        ]

        # 9. 빈 결과: scene 태그도 캐릭터도 없으면 의미 없는 프롬프트.
        #    캐릭터가 0명이면 scene만 있어도 유효 (배경 프롬프트).
        if not scene.tags and not characters:
            raise CompilerEmptyResultError("no scene tags or characters in compile result")

        # 10. warnings = 관계 경고 + unresolved 요약 1줄
        warnings = list(rel_warnings)
        if unresolved:
            warnings.append(
                f"{len(unresolved)} unresolved concept(s) were not added to the final prompt: "
                f"{', '.join(unresolved)}"
            )

        return CompiledPrompt(
            base_prompt=base,
            negative_prompt=negative,
            scene=scene,
            characters=tuple(characters),
            relationships=tuple(relationships),
            mode=mode,
            warnings=tuple(warnings),
            unresolved=tuple(unresolved),
        )

    def close(self) -> None:
        """내장 추론 provider와 자동 기동된 llama-server의 리소스를 해제한다.

        close()가 없는 provider(HTTP 기반)는 아무 일도 하지 않는다.
        """
        close = getattr(self._parser.provider, "close", None)
        if callable(close):
            close()
        if self._server_manager is not None:
            self._server_manager.close()

    def _resolve_tags(self, phrases: list[str]) -> tuple[list[TagRef], list[str]]:
        """후보 문구 목록 → (verified/inferred TagRef 목록, unresolved 태그명 목록).

        use_resolver=False면 LLM 원문을 그대로 verified로 처리 (태그 검증 끄기).
        빈 문구는 건너뛴다. [Minor #1] 같은 태그가 여러 번 나오면 첫 번째만
        유지한다 (LLM 중복 출력 대비, 순서 보존).
        """
        refs: list[TagRef] = []
        unresolved: list[str] = []
        seen: set[str] = set()
        for phrase in phrases:
            phrase = phrase.strip()
            if not phrase:
                continue
            if self.use_resolver:
                for ref in self._resolver.resolve_phrase(phrase):
                    if ref.status in _OK_STATUSES:
                        if ref.tag not in seen:
                            seen.add(ref.tag)
                            refs.append(ref)
                    else:
                        unresolved.append(ref.tag)
            else:
                if phrase not in seen:
                    seen.add(phrase)
                    refs.append(TagRef(tag=phrase, status="verified"))
        return refs, unresolved


def build_compiler(settings) -> PromptCompiler:
    """AppSettings(duck-typed) → PromptCompiler.

    ``settings``는 다음 필드를 가진 객체라면 무엇이든 된다 (없으면 기본값):
    - ``settings.prompt_ai``: provider/base_url/model/temperature/max_tokens/timeout_seconds
    - ``settings.compiler``: use_danbooru_resolver/preserve_natural_language/relationship_style
    - ``settings.tag_database_path``: 태그 DB 경로 (빈 값 = 내장 DB)

    API 키는 keyring(``core.settings.credentials``)에서 ``API_KEY_CREDENTIAL``
    키로 읽는다 — keyring을 쓸 수 없는 환경에서는 빈 키로 동작한다.
    provider 설정 미완료(예: ollama인데 model 비어 있음)는 기본값으로 보정한다.
    """
    ai = getattr(settings, "prompt_ai", None)
    comp = getattr(settings, "compiler", None)
    if ai is None:
        ai = SimpleNamespace()
    if comp is None:
        comp = SimpleNamespace()

    provider_name = getattr(ai, "provider", "") or "openai_compatible"
    base_url = getattr(ai, "base_url", "") or ""
    model = getattr(ai, "model", "") or ""
    # 온전성 보정: ollama는 model 생략 시 기본 모델명 사용
    if provider_name == "ollama" and not model:
        model = "llama3"
    api_key = load_credential(API_KEY_CREDENTIAL)

    provider = create_provider(
        provider=provider_name,
        base_url=base_url,
        model=model,
        api_key=api_key,
        # llama_cpp 전용 — 다른 provider에서는 무시된다 (create_provider의 **extra).
        model_path=getattr(ai, "model_path", "") or "",
        n_ctx=int(getattr(ai, "n_ctx", 16384) or 16384),
        n_gpu_layers=int(getattr(ai, "n_gpu_layers", 99) or 99),
        n_cpu_moe=int(getattr(ai, "n_cpu_moe", 0) or 0),
        expert_hot_s=int(getattr(ai, "expert_hot_s", 0) or 0),
        # DeepSeek 전용 — 다른 provider에서는 무시된다.
        thinking_enabled=bool(getattr(ai, "thinking_enabled", True)),
        reasoning_effort=getattr(ai, "reasoning_effort", "") or "medium",
    )

    use_resolver = bool(getattr(comp, "use_danbooru_resolver", True))
    db_path = getattr(settings, "tag_database_path", "") or None
    # 빈 설정 = 앱에 동봉된 기본 태그 DB로 해석 (TagResolver.load도 같은 규칙을 쓴다).
    resolver = TagResolver(database_path=resolve_database_path(db_path))
    if use_resolver:
        resolver.load()  # 실패 시 내부적으로 비활성

    # RAG 리트리버 — resolver와 같은 DB를 사용한다. 로드 실패 시 검색 비활성(폴백).
    retriever = TagRetriever(database_path=resolve_database_path(db_path))
    retriever.load()

    # llama-server 자동 기동 (openai_compatible + auto_start_server).
    # ensure_running 실패는 치명적이지 않다 — 기존 서버가 있으면 재사용되고,
    # 없으면 provider 호출 시 연결 오류로 안내된다.
    server_manager = None
    if provider_name == "openai_compatible" and bool(getattr(ai, "auto_start_server", False)):
        from .providers.server_manager import LlamaServerManager

        server_manager = LlamaServerManager(
            server_path=getattr(ai, "server_path", "") or "",
            args=getattr(ai, "server_args", "") or "",
            base_url=base_url,
        )
        try:
            server_manager.ensure_running()
        except CompilerError:
            server_manager = None  # 폴백 — 컴파일러는 연결 오류로 동작

    formatter = PromptFormatter(
        preserve_natural_language=bool(getattr(comp, "preserve_natural_language", True)),
        relationship_style=getattr(comp, "relationship_style", "natural"),
    )

    return PromptCompiler(
        provider=provider,
        resolver=resolver,
        formatter=formatter,
        temperature=float(getattr(ai, "temperature", 0.3)),
        max_tokens=int(getattr(ai, "max_tokens", 2048)),
        timeout=float(getattr(ai, "timeout_seconds", 120.0)),
        use_resolver=use_resolver,
        retriever=retriever,
        server_manager=server_manager,
    )
