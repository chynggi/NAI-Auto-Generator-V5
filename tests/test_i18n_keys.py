"""번역 파일 4종의 키 집합이 같아야 한다."""

import json
from pathlib import Path

LANG_DIR = Path(__file__).resolve().parent.parent / "src" / "naiauto" / "resources" / "languages"


def _flat(node, prefix=""):
    out = set()
    for key, value in node.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out |= _flat(value, f"{path}.")
        else:
            out.add(path)
    return out


def test_all_languages_share_the_same_keys():
    sets = {}
    for path in sorted(LANG_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        sets[path.stem] = _flat(data["translations"])
    reference = sets["ko"]
    for name, keys in sets.items():
        assert keys == reference, f"{name}: 누락 {reference - keys}, 잉여 {keys - reference}"


def test_local_backend_keys_exist():
    data = json.loads((LANG_DIR / "ko.json").read_text(encoding="utf-8"))
    options = data["translations"]["options"]
    assert "local_backend_url" in options
    assert "local_backend" in data["translations"]["options_nav"]
