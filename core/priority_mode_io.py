from __future__ import annotations

import os
import json


def _default_file() -> str:
    """保存到项目根目录 priority_mode.json。"""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base_dir, "priority_mode.json")


PRIORITY_MODE_FILE = _default_file()


def load_priority_mode(default: str = "A") -> str:
    """读取优先模式：返回 'A' 或 'B'。"""
    try:
        if not os.path.exists(PRIORITY_MODE_FILE):
            return default
        with open(PRIORITY_MODE_FILE, "r", encoding="utf-8") as f:
            obj = json.load(f)
        mode = str(obj.get("priority_mode", default)).upper().strip()
        return mode if mode in ("A", "B") else default
    except Exception:
        return default


def save_priority_mode(mode: str) -> None:
    """保存优先模式：mode 只能是 'A' 或 'B'。"""
    m = str(mode).upper().strip()
    if m not in ("A", "B"):
        m = "A"
    os.makedirs(os.path.dirname(PRIORITY_MODE_FILE), exist_ok=True)
    with open(PRIORITY_MODE_FILE, "w", encoding="utf-8") as f:
        json.dump({"priority_mode": m}, f, ensure_ascii=False, indent=2)
