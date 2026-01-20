import os
import json
from typing import Dict


def _default_file() -> str:
    # 与 core/keyword_io 同目录放置时：项目根目录下的 zhuli_keywords.py
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base_dir, "zhuli_keywords.py")


ZHULI_KEYWORDS_FILE = _default_file()


def load_zhuli_keywords() -> Dict[str, dict]:
    """读取助播关键词配置（zhuli_keywords.py -> dict）。"""
    if not os.path.exists(ZHULI_KEYWORDS_FILE):
        return {}

    # 直接执行 python 文件，获得 ZHULI_KEYWORDS
    data: Dict[str, dict] = {}
    g: Dict[str, object] = {}
    try:
        with open(ZHULI_KEYWORDS_FILE, "r", encoding="utf-8") as f:
            code = f.read()
        exec(compile(code, ZHULI_KEYWORDS_FILE, "exec"), g)
        raw = g.get("ZHULI_KEYWORDS", {})
        if isinstance(raw, dict):
            data = raw
    except Exception:
        return {}

    # 兜底补字段
    for k, v in list(data.items()):
        if not isinstance(v, dict):
            data.pop(k, None)
            continue
        v.setdefault("priority", 0)
        v.setdefault("must", [])
        v.setdefault("any", [])
        v.setdefault("deny", [])
        v.setdefault("prefix", k)

    return data


def save_zhuli_keywords(data: Dict[str, dict]) -> None:
    """保存到 zhuli_keywords.py（可读性强，便于你手动改）。"""
    # 规范化
    out = {}
    for k, v in (data or {}).items():
        if not isinstance(v, dict):
            continue
        out[k] = {
            "priority": int(v.get("priority", 0) or 0),
            "must": list(v.get("must", []) or []),
            "any": list(v.get("any", []) or []),
            "deny": list(v.get("deny", []) or []),
            "prefix": str(v.get("prefix", k) or k),
        }

    text = "# 助播关键词配置\nZHULI_KEYWORDS = " + json.dumps(out, ensure_ascii=False, indent=4)

    with open(ZHULI_KEYWORDS_FILE, "w", encoding="utf-8") as f:
        f.write(text)


def merge_zhuli_keywords(base: Dict[str, dict], incoming: Dict[str, dict]) -> Dict[str, dict]:
    """合并：incoming 覆盖 base 同 key 字段（不破坏未提供字段）。"""
    base = dict(base or {})
    for k, inc in (incoming or {}).items():
        if k not in base or not isinstance(base.get(k), dict):
            base[k] = inc
        else:
            base[k].update(inc)
    return base
