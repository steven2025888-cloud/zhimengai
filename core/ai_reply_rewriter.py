# core/ai_reply_rewriter.py
from __future__ import annotations

from typing import Any, Dict, Optional
import json
import re
import http.client


# ---------- runtime_state ----------
def _load_runtime_state() -> Dict[str, Any]:
    try:
        from core.runtime_state import load_runtime_state  # 你的项目里正常应当有
        if callable(load_runtime_state):
            return load_runtime_state() or {}
    except Exception:
        pass
    return {}


# ---------- config ----------
def _cfg_get(*names: str, default: str = "") -> str:
    try:
        import config  # type: ignore
        for n in names:
            v = getattr(config, n, None)
            if isinstance(v, str) and v.strip():
                return v.strip()
    except Exception:
        pass
    return default


def _ensure_punct_and_trim(s: str, max_chars: int = 50) -> str:
    s = (s or "").strip()
    if not s:
        return ""

    # 去掉多余引号/换行
    s = s.replace("\r", " ").replace("\n", " ").strip()
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip("“”\"'` ")

    # 超长截断
    if len(s) > max_chars:
        s = s[:max_chars].rstrip()

    # 末尾没标点就补一个
    if s and s[-1] not in "。！？!?，,.;；":
        s += "。"

    # 再次兜底长度
    if len(s) > max_chars:
        s = s[:max_chars].rstrip("，,.;；")
        if s and s[-1] not in "。！？!?":
            s += "。"
        s = s[:max_chars]

    return s


def rewrite_keyword_reply_if_enabled(reply_text: str, max_chars: int = 50) -> str:
    """
    ✅ 当 runtime_state.json: ai_reply == true 时，将 reply_text 丢给模型改写后返回。
    - 要求：带标点、<=50字（默认 max_chars=50）
    - 失败/超时/没key：直接返回原文（也会做标点&截断兜底）
    """
    base = _ensure_punct_and_trim(reply_text, max_chars=max_chars)
    if not base:
        return ""

    st = _load_runtime_state()
    if not bool(st.get("ai_reply", False)):
        return base

    api_key = str(st.get("ai_api_key") or "").strip()
    model = str(st.get("ai_model") or "").strip()
    if not api_key or not model:
        return base

    host = _cfg_get("AI_API_HOST", "DPS_API_HOST", default="api.openai.com")
    path = _cfg_get("AI_API_PATH", "DPS_API_PATH", default="/v1/chat/completions")

    prompt = (
        "你是直播间客服回复改写助手。"
        "请把下面这句“回复词”改写成更自然、更口语的客服回复，保持原意。"
        f"要求：1) 必须有合适标点；2) 不超过{max_chars}个字/字符；3) 只输出改写后的句子，不要解释。\n"
        f"回复词：{base}"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你只输出最终改写句子，不要解释。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        # 你 UI 测试线程也是这么连的（https + chat/completions 思路一致）:contentReference[oaicite:4]{index=4}
        conn = http.client.HTTPSConnection(host, timeout=8)
        conn.request("POST", path, body=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", "ignore")
        if not (200 <= resp.status < 300):
            return base

        data = json.loads(raw) if raw else {}
        txt = (
            (data.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        out = _ensure_punct_and_trim(str(txt), max_chars=max_chars)
        return out or base
    except Exception:
        return base
