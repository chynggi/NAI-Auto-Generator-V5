"""``/object_info`` 응답 파싱.

서버가 어떤 노드와 어떤 선택지를 갖고 있는지 알려주는 유일한 창구다. 이 앱은
두 가지에 쓴다: 템플릿의 ``requires_nodes`` 충족 여부 판단, 그리고 모델·샘플러
목록 채우기.

응답 모양은 ``{"NodeClass": {"input": {"required": {"name": [<옵션>, {...}]}}}}``이고,
``<옵션>``이 리스트면 콤보(선택지), 문자열이면 스칼라 타입("INT" 등)이다.

서버 버전에 따라 모양이 어긋날 수 있으므로 모든 접근을 방어적으로 한다 —
목록을 못 읽는 것과 앱이 죽는 것은 전혀 다른 문제다. Qt 의존성 없음.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ObjectInfo", "parse_object_info"]


@dataclass(frozen=True)
class ObjectInfo:
    """서버가 아는 노드 클래스와 입력 선택지."""

    node_classes: frozenset[str]
    #: "NodeClass.input_name" → 선택지 튜플
    _options: dict[str, tuple[str, ...]]

    @classmethod
    def empty(cls) -> ObjectInfo:
        """서버에 못 붙었을 때 쓰는 빈 정보."""
        return cls(node_classes=frozenset(), _options={})

    def options(self, path: str) -> tuple[str, ...]:
        """"NodeClass.input_name" → 선택지. 없으면 빈 튜플."""
        return self._options.get(path, ())


def parse_object_info(raw: object) -> ObjectInfo:
    """``/object_info`` JSON → ``ObjectInfo``. 어떤 입력에도 예외를 내지 않는다."""
    if not isinstance(raw, dict):
        return ObjectInfo.empty()
    options: dict[str, tuple[str, ...]] = {}
    for node_class, spec in raw.items():
        if not isinstance(spec, dict):
            continue
        inputs = spec.get("input")
        if not isinstance(inputs, dict):
            continue
        for section in ("required", "optional"):
            fields = inputs.get(section)
            if not isinstance(fields, dict):
                continue
            for input_name, definition in fields.items():
                if not isinstance(definition, list) or not definition:
                    continue
                choices = definition[0]
                # 리스트면 콤보, 문자열이면 스칼라 타입("INT" 등)이다.
                if isinstance(choices, list):
                    options[f"{node_class}.{input_name}"] = tuple(
                        str(c) for c in choices
                    )
    return ObjectInfo(node_classes=frozenset(map(str, raw)), _options=options)
