# core/zhuli_keyword_io.py
from __future__ import annotations

from typing import Dict, Any
import os
import sys
import importlib
import importlib.util
import pprint

KEY = "zhuli_keywords"  # 保留常量名，避免外部引用报错（但不再使用 runtime_state）


def _normalize(data: Dict[str, Any]) -> Dict[str, dict]:
    """补齐字段/清理脏数据，确保结构稳定。"""
    out: Dict[str, dict] = {}
    for k, v in (data or {}).items():
        if not isinstance(v, dict):
            continue
        prefix = str(v.get("prefix") or k).strip()
        if not prefix:
            continue
        vv = dict(v)
        vv.setdefault("priority", 0)
        vv.setdefault("must", [])
        vv.setdefault("any", [])
        vv.setdefault("deny", [])
        vv.setdefault("reply", [])
        vv["prefix"] = prefix
        out[prefix] = vv
    return out


def _get_zhuli_keywords_py_path() -> str:
    """
    获取 zhuli_keywords.py 的真实路径：
    - 优先通过 importlib 找到模块文件位置
    - 找不到就退化到当前工作目录下的 zhuli_keywords.py
    """
    spec = importlib.util.find_spec("zhuli_keywords")
    if spec and spec.origin and spec.origin.endswith(".py") and os.path.exists(spec.origin):
        return spec.origin

    # fallback: 运行目录
    guess = os.path.join(os.getcwd(), "zhuli_keywords.py")
    return guess


def load_zhuli_keywords() -> Dict[str, dict]:
    """
    只从 zhuli_keywords.py 读取（不再读取/迁移/写入 runtime_state.json）。
    """
    try:
        # 为了“实时更新”，尽量 reload 一次
        import zhuli_keywords  # type: ignore
        importlib.reload(zhuli_keywords)  # type: ignore

        py_data = getattr(zhuli_keywords, "ZHULI_KEYWORDS", {})  # type: ignore
        if not isinstance(py_data, dict):
            py_data = {}
        return _normalize(py_data)
    except Exception:
        return {}


def save_zhuli_keywords(data: Dict[str, dict]) -> None:
    """
    只保存到 zhuli_keywords.py（下次启动仍保留），不再写 runtime_state.json。
    """
    path = _get_zhuli_keywords_py_path()
    norm = _normalize(data or {})

    # 生成可读性更好的 python 文件内容
    body = pprint.pformat(norm, width=140, sort_dicts=False)

    content = (
        "# -*- coding: utf-8 -*-\n"
        "# 自动生成：助理关键词配置（ZHULI_KEYWORDS）\n"
        "# 请勿手动修改格式（可在程序内编辑/导入导出）\n\n"
        f"ZHULI_KEYWORDS = {body}\n"
    )

    # 确保目录存在
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    # 写入文件
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    # 写完后让 import 读取新内容
    importlib.invalidate_caches()
    if "zhuli_keywords" in sys.modules:
        try:
            importlib.reload(sys.modules["zhuli_keywords"])
        except Exception:
            pass


def merge_zhuli_keywords(base: Dict[str, dict], incoming: Dict[str, dict]) -> Dict[str, dict]:
    base = _normalize(base or {})
    inc = _normalize(incoming or {})
    base.update(inc)
    return base
