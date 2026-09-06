"""/object_info 파싱 테스트 — 실제 응답 모양을 축약한 픽스처로 검증한다."""

import pytest

from naiauto.core.backends.comfy_objects import ObjectInfo, parse_object_info

#: 실제 /object_info 응답의 모양 (필요한 부분만).
RAW = {
    "CheckpointLoaderSimple": {
        "input": {"required": {"ckpt_name": [["wai.safetensors", "other.safetensors"], {}]}}
    },
    "KSampler": {
        "input": {
            "required": {
                "seed": ["INT", {"default": 0}],
                "sampler_name": [["euler", "euler_ancestral", "dpmpp_2m"], {}],
                "scheduler": [["normal", "karras", "simple"], {}],
            }
        }
    },
    "UNETLoader": {
        "input": {"required": {"unet_name": [["Anima-2.9B-preview-v1.safetensors"], {}]}}
    },
    "PreviewImage": {"input": {"required": {"images": ["IMAGE", {}]}}},
}


def test_node_classes_lists_every_key():
    info = parse_object_info(RAW)
    assert "KSampler" in info.node_classes
    assert "UNETLoader" in info.node_classes


def test_options_reads_combo_lists():
    info = parse_object_info(RAW)
    assert info.options("CheckpointLoaderSimple.ckpt_name") == (
        "wai.safetensors",
        "other.safetensors",
    )
    assert info.options("KSampler.sampler_name") == ("euler", "euler_ancestral", "dpmpp_2m")
    assert info.options("KSampler.scheduler") == ("normal", "karras", "simple")


def test_options_empty_for_non_combo_input():
    """INT 같은 스칼라 입력은 선택지가 없다."""
    info = parse_object_info(RAW)
    assert info.options("KSampler.seed") == ()


def test_options_empty_for_unknown_paths():
    info = parse_object_info(RAW)
    assert info.options("NoSuchNode.foo") == ()
    assert info.options("KSampler.no_such_input") == ()
    assert info.options("malformed") == ()


def test_parse_tolerates_garbage():
    """서버 버전이 달라 모양이 어긋나도 크래시하면 안 된다."""
    assert parse_object_info({}).node_classes == frozenset()
    assert parse_object_info({"X": "not a dict"}).options("X.y") == ()
    assert parse_object_info({"X": {"input": None}}).options("X.y") == ()


def test_empty_info_is_falsy_and_usable():
    info = ObjectInfo.empty()
    assert not info.node_classes
    assert info.options("KSampler.sampler_name") == ()


@pytest.mark.parametrize(
    "raw",
    [
        None, 0, "", [], "not json", {"A": None}, {"A": []}, {"A": {"input": None}},
        {"A": {"input": {"required": None}}}, {"A": {"input": {"required": {"x": None}}}},
        {"A": {"input": {"required": {"x": []}}}}, {"A": {"input": {"required": {"x": [[]]}}}},
        {"A": {"input": {"required": {"x": [[1, 2]]}}}},
        {"A": {"input": {"optional": {"x": [["a"]]}}}},
    ],
)
def test_parse_never_raises(raw):
    """외부 서버 응답이다 — 어떤 모양이 와도 예외를 내면 옵션 창이 죽는다."""
    info = parse_object_info(raw)
    assert isinstance(info.node_classes, frozenset)
    assert isinstance(info.options("A.x"), tuple)
