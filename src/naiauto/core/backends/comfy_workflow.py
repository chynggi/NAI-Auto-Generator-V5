"""ComfyUI 워크플로 템플릿 — 로딩·검증·값 주입.

ComfyUI에는 "프롬프트를 보내는" API가 없다. 노드 그래프(API 형식) 전체를 큐에
넣는 구조라, 그래프를 어디서 가져오고 값을 어디에 넣을지가 정해져야 한다.

우리가 저작한 템플릿을 리소스로 동봉하고, 매니페스트가 주입 지점을 선언한다.
노드 제목(``_meta.title``) 규칙은 쓰지 않는다 — 제목은 ComfyUI UI에서 자유롭게
바뀌므로 조용히 깨진다.

``model_slots``는 템플릿마다 개수와 이름이 다르다. SDXL은 ``checkpoint`` 하나,
Anima는 UNET+CLIP+VAE 세 개다. 그래서 고정 집합이 아니라 템플릿이 선언한다.

주입은 순수 계산이고 로딩만 I/O다 — 그래야 서버 없이 테스트할 수 있다.
Qt 의존성 없음.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from naiauto.core.backends.errors import ComfyTemplateError

logger = logging.getLogger(__name__)

__all__ = [
    "LORA_MODES",
    "LoraAssignment",
    "ModelSlot",
    "WorkflowTemplate",
    "build_graph",
    "builtin_workflows_dir",
    "parse_template",
    "load_workflows",
    "find_workflow",
    "strip_lora_tags",
]

#: ``lora_mode`` 유효값.
#: direct   — 앱이 LoraLoader 체인을 그래프에 넣고 프롬프트에서 <lora:...>를 뺀다
#: delegate — 프롬프트를 그대로 넘긴다 (PCLazyLoraLoader가 알아서 한다)
LORA_MODES = ("direct", "delegate")


@dataclass(frozen=True)
class ModelSlot:
    """모델 파일을 넣을 자리 하나."""

    #: 그래프 안 위치 — "<node_id>.<input_name>"
    path: str
    #: /object_info 조회 경로 — "<NodeClass>.<input_name>"
    source: str


@dataclass(frozen=True)
class WorkflowTemplate:
    """워크플로 템플릿 1개 (매니페스트 + 그래프)."""

    id: str
    name: str
    output_node: str
    #: 원본 그래프. frozen 데이터클래스지만 이 dict 자체는 가변이고 템플릿마다
    #: 하나뿐이다 — 값을 주입할 때는 반드시 깊은 복사를 먼저 해야 한다.
    #: 얕은 복사(dict(...))는 중첩된 inputs를 공유해 원본을 오염시킨다.
    graph: dict
    slots: dict[str, str] = field(default_factory=dict)
    model_slots: dict[str, ModelSlot] = field(default_factory=dict)
    requires_nodes: tuple[str, ...] = ()
    lora_mode: str = "direct"

    def is_available(self, known_node_classes: Iterable[str]) -> bool:
        """``requires_nodes``가 전부 서버에 있으면 True."""
        known = set(known_node_classes)
        return all(node in known for node in self.requires_nodes)


def builtin_workflows_dir() -> Path:
    """패키지에 동봉된 템플릿 폴더 (다른 리소스와 같은 규칙)."""
    return Path(__file__).resolve().parent.parent.parent / "resources" / "comfy_workflows"


def _split_path(path: str, what: str) -> tuple[str, str]:
    """"3.seed" → ("3", "seed"). 형식이 아니면 ComfyTemplateError."""
    parts = str(path).split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ComfyTemplateError(f"{what}: {path!r} must be '<node_id>.<input_name>'")
    return parts[0], parts[1]


def _check_path(graph: dict, path: str, what: str) -> None:
    """슬롯 경로가 그래프에 실재하는지 확인한다.

    로드 시점에 잡아야 한다 — 런타임에 드러나면 사용자가 생성 실패로만 본다.
    """
    node_id, input_name = _split_path(path, what)
    node = graph.get(node_id)
    if not isinstance(node, dict):
        raise ComfyTemplateError(f"{what}: node {node_id!r} not in graph")
    if input_name not in node.get("inputs", {}):
        raise ComfyTemplateError(f"{what}: node {node_id!r} has no input {input_name!r}")


def parse_template(data: dict) -> WorkflowTemplate:
    """템플릿 JSON 1개 → ``WorkflowTemplate``. 위반 시 ``ComfyTemplateError``."""
    if not isinstance(data, dict):
        raise ComfyTemplateError("template must be a JSON object")
    template_id = str(data.get("id", "")).strip()
    if not template_id:
        raise ComfyTemplateError("template needs a non-empty 'id'")
    graph = data.get("graph")
    if not isinstance(graph, dict) or not graph:
        raise ComfyTemplateError(f"{template_id}: 'graph' must be a non-empty object")

    output_node = str(data.get("output_node", "")).strip()
    if output_node not in graph:
        raise ComfyTemplateError(
            f"{template_id}: 'output_node' {output_node!r} not in graph"
        )

    lora_mode = str(data.get("lora_mode", "direct"))
    if lora_mode not in LORA_MODES:
        raise ComfyTemplateError(
            f"{template_id}: 'lora_mode' must be one of {LORA_MODES}, got {lora_mode!r}"
        )

    raw_slots = data.get("slots", {})
    if not isinstance(raw_slots, dict):
        raise ComfyTemplateError(f"{template_id}: 'slots' must be an object")
    slots: dict[str, str] = {}
    for name, path in raw_slots.items():
        _check_path(graph, str(path), f"{template_id}.slots.{name}")
        slots[str(name)] = str(path)

    raw_models = data.get("model_slots", {})
    if not isinstance(raw_models, dict):
        raise ComfyTemplateError(f"{template_id}: 'model_slots' must be an object")
    model_slots: dict[str, ModelSlot] = {}
    for name, spec in raw_models.items():
        if not isinstance(spec, dict) or "path" not in spec or "from" not in spec:
            raise ComfyTemplateError(
                f"{template_id}.model_slots.{name}: needs 'path' and 'from'"
            )
        _check_path(graph, str(spec["path"]), f"{template_id}.model_slots.{name}")
        _split_path(str(spec["from"]), f"{template_id}.model_slots.{name}.from")
        model_slots[str(name)] = ModelSlot(path=str(spec["path"]), source=str(spec["from"]))

    requires = data.get("requires_nodes", [])
    if not isinstance(requires, list) or any(not isinstance(n, str) for n in requires):
        raise ComfyTemplateError(f"{template_id}: 'requires_nodes' must be a list of strings")

    return WorkflowTemplate(
        id=template_id,
        name=str(data.get("name", "")).strip() or template_id,
        output_node=output_node,
        graph=graph,
        slots=slots,
        model_slots=model_slots,
        requires_nodes=tuple(requires),
        lora_mode=lora_mode,
    )


def _load_dir(directory: Path) -> list[WorkflowTemplate]:
    """폴더의 ``*.json``을 템플릿으로 읽는다. 깨진 파일은 건너뛴다."""
    templates: list[WorkflowTemplate] = []
    try:
        if not directory.is_dir():
            return templates
        paths = sorted(directory.glob("*.json"))
    except OSError as exc:
        logger.warning("cannot read workflow directory %s: %s", directory, exc)
        return templates
    for path in paths:
        try:
            templates.append(parse_template(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError, ValueError, ComfyTemplateError) as exc:
            logger.warning("skipping broken workflow template %s: %s", path, exc)
    return templates


def load_workflows(user_dir: str | Path | None = None) -> tuple[WorkflowTemplate, ...]:
    """내장 + 사용자 템플릿. 같은 id면 사용자 것이 이긴다."""
    ordered: dict[str, WorkflowTemplate] = {}
    for template in _load_dir(builtin_workflows_dir()):
        ordered[template.id] = template
    text = str(user_dir).strip() if user_dir is not None else ""
    if text:
        for template in _load_dir(Path(text)):
            ordered[template.id] = template
    return tuple(ordered.values())


def find_workflow(
    templates: tuple[WorkflowTemplate, ...], template_id: str
) -> WorkflowTemplate | None:
    """id로 템플릿을 찾는다. 없으면 None (호출자가 안내를 정한다)."""
    for template in templates:
        if template.id == template_id:
            return template
    return None


#: 프롬프트에서 걷어낼 <lora:name:weight> 태그.
#: 파일명에 괄호가 들어갈 수 있어(hans_anima-kei_(blue_archive)_lora) ">"가 아닌
#: 모든 문자를 받는다.
_LORA_TAG_RE = re.compile(r"<lora:[^>]*>")

#: 태그를 뺀 자리에 남는 쉼표/공백 정리.
_TIDY_RE = re.compile(r"\s*,\s*")


@dataclass(frozen=True)
class LoraAssignment:
    """그래프에 결선할 LoRA 하나."""

    file: str
    weight: float = 1.0


def strip_lora_tags(text: str) -> str:
    """프롬프트에서 ``<lora:...>``를 빼고 남은 쉼표를 정리한다.

    기본 ComfyUI의 ``CLIPTextEncode``는 이 문법을 파싱하지 않고 그냥 문자열로
    인코딩한다 — 남겨 두면 결과를 오염시킨다.
    """
    cleaned = _LORA_TAG_RE.sub("", text)
    cleaned = _TIDY_RE.sub(", ", cleaned)
    return cleaned.strip().strip(",").strip()


def _next_node_id(graph: dict) -> str:
    """그래프에서 쓰이지 않은 숫자 노드 id."""
    used = {int(k) for k in graph if str(k).isdigit()}
    return str(max(used, default=0) + 1)


def _insert_lora_chain(
    graph: dict, template: WorkflowTemplate, loras: tuple[LoraAssignment, ...]
) -> None:
    """모델/CLIP 소비자들 앞에 ``LoraLoader`` 체인을 끼워 넣는다.

    체크포인트(또는 UNET) 출력을 받던 노드들이 대신 체인 끝을 받도록 재결선한다.
    ``delegate`` 모드에서는 부르지 않는다 — 확장이 같은 일을 하므로 두 번 걸린다.
    """
    if not loras:
        return
    # 체인의 시작점: 지금 model/clip을 내보내는 링크를 찾는다.
    model_src = None
    clip_src = None
    for node in graph.values():
        inputs = node.get("inputs", {})
        if model_src is None and isinstance(inputs.get("model"), list):
            model_src = list(inputs["model"])
        if clip_src is None and isinstance(inputs.get("clip"), list):
            clip_src = list(inputs["clip"])
    if model_src is None or clip_src is None:
        logger.warning(
            "%s: cannot find model/clip links to splice LoRA into, skipping", template.id
        )
        return
    # 원본 출처를 기억해 둔다 — 재결선 대상을 이걸로 고른다 (아래 참고).
    origin_model = list(model_src)
    origin_clip = list(clip_src)

    chain_ids: set[str] = set()
    for lora in loras:
        node_id = _next_node_id(graph)
        graph[node_id] = {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": lora.file,
                "strength_model": lora.weight,
                "strength_clip": lora.weight,
                "model": model_src,
                "clip": clip_src,
            },
        }
        chain_ids.add(node_id)
        model_src = [node_id, 0]
        clip_src = [node_id, 1]

    # 체인 뒤로 재결선.
    #
    # **원본 출처를 그대로 받던 노드만** 바꾼다. "class_type이 LoraLoader가 아닌
    # 노드 전부"로 거르면 안 된다 — Anima 템플릿에는 UNET에서 model을 받는
    # LoraLoaderModelOnly(터보 LoRA) 노드가 있는데, class_type이 정확히
    # "LoraLoader"가 아니라 그 필터를 빠져나가 체인 끝을 가리키게 된다. 그러면
    # 터보 노드와 체인 첫 노드가 서로를 가리키는 순환이 생기고 ComfyUI가 그래프를
    # 거부한다.
    #
    # 우리가 방금 만든 로더는 id로 건너뛴다 — 체인 첫 노드의 model이 원본과
    # 같으므로 값으로만 거르면 자기 자신을 자기 뒤로 돌린다.
    for node_id, node in graph.items():
        if node_id in chain_ids:
            continue
        inputs = node.get("inputs", {})
        if inputs.get("model") == origin_model:
            inputs["model"] = list(model_src)
        if inputs.get("clip") == origin_clip:
            inputs["clip"] = list(clip_src)


def build_graph(
    template: WorkflowTemplate,
    *,
    values: dict | None = None,
    models: dict[str, str] | None = None,
    loras: tuple[LoraAssignment, ...] = (),
) -> dict:
    """템플릿 + 값 → 큐에 넣을 그래프 (깊은 복사본).

    템플릿은 앱 수명 내내 재사용되므로 **원본을 절대 건드리지 않는다.**
    선언되지 않은 슬롯과 None/빈 값은 조용히 건너뛴다 — 템플릿마다 슬롯이 달라
    호출자가 전부를 알 수 없다.
    """
    values = values or {}
    models = models or {}
    graph = copy.deepcopy(template.graph)

    prompt_values = dict(values)
    if template.lora_mode == "direct":
        for key in ("positive", "negative"):
            if isinstance(prompt_values.get(key), str):
                prompt_values[key] = strip_lora_tags(prompt_values[key])
        _insert_lora_chain(graph, template, loras)

    for name, path in template.slots.items():
        if name not in prompt_values or prompt_values[name] is None:
            continue
        node_id, input_name = _split_path(path, f"{template.id}.slots.{name}")
        graph[node_id]["inputs"][input_name] = prompt_values[name]

    for name, slot in template.model_slots.items():
        chosen = models.get(name, "")
        if not chosen:
            continue
        node_id, input_name = _split_path(slot.path, f"{template.id}.model_slots.{name}")
        graph[node_id]["inputs"][input_name] = chosen

    return graph
