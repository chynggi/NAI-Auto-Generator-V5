"""백엔드 전환 — 서비스 재결선, 콤보 목록 교체, Anlas 숨김."""

import pytest

from naiauto.core.api.models import GenerationResult


class _Local:
    supports_credit = False

    def generate(self, req):  # pragma: no cover
        return GenerationResult(raw_bytes=b"")


def test_service_backend_can_be_swapped():
    from naiauto.services.generation_service import GenerationService

    class _Nai:
        def generate(self, req):  # pragma: no cover
            return GenerationResult(raw_bytes=b"")

        def get_anlas(self):
            return {}

    nai = _Nai()
    service = GenerationService(nai)
    assert service.backend is nai
    local = _Local()
    service.set_backend(local)
    assert service.backend is local
    service.shutdown()


def test_backend_cannot_be_swapped_while_running():
    """생성 중에 백엔드를 갈아 끼우면 진행 중인 잡이 엉뚱한 서버를 본다."""
    from naiauto.services.generation_service import GenerationService

    service = GenerationService(_Local())
    service._running = True
    with pytest.raises(RuntimeError):
        service.set_backend(_Local())
    service._running = False
    service.shutdown()
