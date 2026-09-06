"""실제 ComfyUI 서버로 1장 생성 — `pytest -m comfy_live`로만 돈다.

환경변수:
  NAIAUTO_COMFY_URL        기본 http://127.0.0.1:8188
  NAIAUTO_COMFY_CHECKPOINT 필수 — 서버에 실재하는 SDXL 체크포인트 파일명
"""

import os

import pytest

pytestmark = pytest.mark.comfy_live


def test_generates_one_image():
    from naiauto.core.api.models import GenerationRequest
    from naiauto.core.backends.comfy_workflow import find_workflow, load_workflows
    from naiauto.core.backends.comfyui import ComfyUIBackend

    checkpoint = os.environ.get("NAIAUTO_COMFY_CHECKPOINT")
    if not checkpoint:
        pytest.skip("NAIAUTO_COMFY_CHECKPOINT가 없다")

    template = find_workflow(load_workflows(), "sdxl_basic")
    assert template is not None

    seen = []
    backend = ComfyUIBackend(
        base_url=os.environ.get("NAIAUTO_COMFY_URL", "http://127.0.0.1:8188"),
        template=template,
        model_slots={"checkpoint": checkpoint},
        timeout=300.0,
        on_progress=lambda v, m: seen.append((v, m)),
    )
    result = backend.generate(
        GenerationRequest(
            prompt="1girl, solo, simple background",
            negative_prompt="worst quality",
            width=512,
            height=512,
            steps=4,
            cfg_scale=5.0,
            sampler="euler",
            scheduler="normal",
            seed=1234,
        )
    )
    assert result.raw_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    assert seen, "진행률 메시지를 하나도 못 받았다"
