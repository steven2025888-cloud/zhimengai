# core/comment_logger.py
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional


_LOCK = threading.Lock()


def _app_base_dir() -> Path:
    """
    尽量和你项目的 runtime_state / get_app_dir 逻辑对齐：
    - 优先用 config.get_app_dir()
    - 其次 frozen -> exe 目录
    - 否则 -> 项目根目录（core/.）
    """
    try:
        import config  # type: ignore
        get_app_dir = getattr(config, "get_app_dir", None)
        if callable(get_app_dir):
            p = Path(str(get_app_dir())).resolve()
            if str(p).strip():
                return p
    except Exception:
        pass

    try:
        import sys
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
    except Exception:
        pass

    return Path(__file__).resolve().parents[1]


def _logs_dir() -> Path:
    d = _app_base_dir() / "logs" / "comments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _log_file() -> Path:
    # ✅ 单文件长期累积（不按日期切分）
    return _logs_dir() / "comment_reply_log.jsonl"


def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def append_event(event: Dict[str, Any]) -> Optional[str]:
    """
    追加一条事件到 jsonl 文件（长期累积）。
    返回写入的文件路径（字符串），便于 UI 展示。
    """
    event = dict(event or {})
    event.setdefault("ts", _ts())

    p = _log_file()
    line = json.dumps(event, ensure_ascii=False)

    try:
        with _LOCK:
            with open(p, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return str(p)
    except Exception as e:
        print("⚠️ 写评论日志失败：", e)
        return None


def log_comment(platform: str, nickname: str, content: str, meta: Optional[Dict[str, Any]] = None) -> Optional[str]:
    return append_event({
        "type": "comment",
        "platform": platform,
        "nickname": nickname or "未知用户",
        "content": content or "",
        "meta": meta or {},
    })


def log_reply(platform: str, to_nickname: str, reply_text: str, meta: Optional[Dict[str, Any]] = None) -> Optional[str]:
    return append_event({
        "type": "reply",
        "platform": platform,
        "nickname": to_nickname or "未知用户",
        "content": reply_text or "",
        "meta": meta or {},
    })


def get_log_path() -> str:
    return str(_log_file())


def clear_log() -> bool:
    """
    ✅ 清空日志：保留文件名，内容清空
    """
    p = _log_file()
    try:
        with _LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write("")
        return True
    except Exception as e:
        print("⚠️ 清空评论日志失败：", e)
        return False


def open_logs_dir_in_explorer() -> None:
    """
    Windows：打开日志目录；其它系统尽量兼容。
    """
    d = _logs_dir()
    try:
        os.startfile(str(d))  # type: ignore[attr-defined]
    except Exception:
        try:
            import subprocess
            subprocess.Popen(["explorer", str(d)])
        except Exception:
            pass
