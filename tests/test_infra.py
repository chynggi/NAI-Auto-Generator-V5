def test_import_naiauto():
    import naiauto  # noqa: F401

    assert True


def test_credit_logging_skipped_for_backend_without_credit():
    """로컬 백엔드는 Anlas 개념이 없다 — 조회를 시도하면 안 된다."""
    from naiauto.core.api.models import GenerationResult
    from naiauto.services.generation_service import GenerationService

    calls = []

    class _LocalBackend:
        supports_credit = False

        def generate(self, req):  # pragma: no cover - 이 테스트에서 안 부른다
            return GenerationResult(raw_bytes=b"")

        def get_anlas(self):
            calls.append("anlas")
            raise AssertionError("로컬 백엔드에서 get_anlas를 부르면 안 된다")

    service = GenerationService(_LocalBackend())
    service._log_credit(1)          # 예외 없이 조용히 지나가야 한다
    assert calls == []
    service.shutdown()


def test_credit_logging_attempted_for_novelai_backend():
    """NAIClient는 플래그를 선언하지 않는다 — 기본값(True)으로 조회를 시도해야 한다."""
    from naiauto.core.api.models import GenerationResult
    from naiauto.services.generation_service import GenerationService

    calls = []

    class _NaiLike:
        def generate(self, req):  # pragma: no cover
            return GenerationResult(raw_bytes=b"")

        def get_anlas(self):
            calls.append("anlas")
            return {}

    service = GenerationService(_NaiLike())
    service._log_credit(1)
    assert calls == ["anlas"]
    service.shutdown()
