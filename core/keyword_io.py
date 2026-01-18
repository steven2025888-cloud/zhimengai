import ast
import json
import os
import re
import importlib
from typing import Dict, Any, List, Tuple
import sys

def resource_path(relative):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.abspath("."), relative)

KEYWORDS_FILE = resource_path("keywords.py")


def _ensure_cfg(prefix: str, cfg: dict) -> dict:
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.setdefault("priority", 0)
    cfg.setdefault("must", [])
    cfg.setdefault("any", [])
    cfg.setdefault("deny", [])
    # ✅新增：回复词（用于弹幕命中后自动回复客户）
    cfg.setdefault("reply", [])
    cfg["prefix"] = prefix
    # 强制类型
    for k in ("must", "any", "deny", "reply"):
        if not isinstance(cfg.get(k), list):
            cfg[k] = []
    try:
        cfg["priority"] = int(cfg.get("priority", 0))
    except Exception:
        cfg["priority"] = 0
    return cfg


def _extract_qa_keywords(py_text: str) -> Dict[str, dict]:
    tree = ast.parse(py_text)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "QA_KEYWORDS":
                    data = ast.literal_eval(node.value)
                    if isinstance(data, dict):
                        return data
    return {}


def load_keywords() -> Dict[str, dict]:
    if not os.path.exists(KEYWORDS_FILE):
        return {}
    with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
        txt = f.read()
    data = _extract_qa_keywords(txt)
    out = {}
    for prefix, cfg in data.items():
        prefix = str(prefix)
        out[prefix] = _ensure_cfg(prefix, cfg)
    return out


def _format_keywords_py(data: Dict[str, dict]) -> str:
    lines = ["QA_KEYWORDS = {\n"]
    items = list(data.items())
    # priority 高的优先排前面；同优先级按名字
    items.sort(key=lambda kv: (-int(kv[1].get("priority", 0)), str(kv[0])))

    for prefix, cfg in items:
        prefix = str(prefix)
        cfg = _ensure_cfg(prefix, cfg)
        lines.append(f'    "{prefix}": {{\n')
        lines.append(f'        "priority": {int(cfg["priority"])},\n')
        lines.append(f'        "must": {repr(cfg["must"])},\n')
        lines.append(f'        "any": {repr(cfg["any"])},\n')
        lines.append(f'        "deny": {repr(cfg["deny"])},\n')
        lines.append(f'        "reply": {repr(cfg["reply"])},\n')
        lines.append(f'        "prefix": "{prefix}"\n')
        lines.append("    },\n")

    lines.append("}\n")
    return "".join(lines)


def save_keywords(data: Dict[str, dict]) -> None:
    txt = _format_keywords_py(data)
    with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
        f.write(txt)


def reload_keywords_hot() -> Dict[str, dict]:
    """
    热加载：更新 runtime 中 keywords.QA_KEYWORDS（不重启立刻生效）
    适配你 main.py 里 from keywords import QA_KEYWORDS 的用法。
    """
    data = load_keywords()
    try:
        import keywords as kw_mod
        # 直接原地更新 dict，保证引用不变
        if isinstance(getattr(kw_mod, "QA_KEYWORDS", None), dict):
            kw_mod.QA_KEYWORDS.clear()
            kw_mod.QA_KEYWORDS.update(data)
        else:
            # 万一不是 dict，就强制重载模块
            importlib.reload(kw_mod)
    except Exception:
        # 不阻断 UI，只返回数据
        pass
    return data


def export_keywords_json(data: Dict[str, dict], filepath: str) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _uniq_extend(dst: List[str], src: List[str]) -> List[str]:
    exist = set(map(str, dst))
    for x in src:
        x = str(x).strip()
        if not x:
            continue
        if x not in exist:
            dst.append(x)
            exist.add(x)
    return dst


def merge_keywords(base: Dict[str, dict], incoming: Dict[str, Any]) -> Dict[str, dict]:
    """
    导入=合并：
    - 新分类直接加入
    - 已存在分类：must/any/deny 去重追加
    - priority：取 max(base, incoming)（更合理：不把你已有高优先级覆盖掉）
    """
    out = {k: _ensure_cfg(k, v) for k, v in base.items()}

    for prefix, cfg in incoming.items():
        prefix = str(prefix)
        cfg = _ensure_cfg(prefix, cfg if isinstance(cfg, dict) else {})
        if prefix not in out:
            out[prefix] = cfg
            continue

        cur = out[prefix]
        cur["priority"] = max(int(cur.get("priority", 0)), int(cfg.get("priority", 0)))
        cur["must"] = _uniq_extend(cur.get("must", []), cfg.get("must", []))
        cur["any"] = _uniq_extend(cur.get("any", []), cfg.get("any", []))
        cur["deny"] = _uniq_extend(cur.get("deny", []), cfg.get("deny", []))
        cur["reply"] = _uniq_extend(cur.get("reply", []), cfg.get("reply", []))
        out[prefix] = _ensure_cfg(prefix, cur)

    return out


def load_keywords_json(filepath: str) -> Dict[str, dict]:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        k = str(k)
        out[k] = _ensure_cfg(k, v if isinstance(v, dict) else {})
    return out
