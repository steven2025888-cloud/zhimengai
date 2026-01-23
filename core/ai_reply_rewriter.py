# core/ai_reply_rewriter.py
from __future__ import annotations

from typing import Any, Dict, Optional
import json
import re
import http.client
from pathlib import Path

# ---------- runtime_state ----------
def _fallback_runtime_state_path() -> Path:
    # ✅ 和你 config.get_app_dir() 一致：frozen 用 exe 目录，源码用项目目录
    try:
        import sys
        from pathlib import Path
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
        else:
            base = Path(__file__).resolve().parents[1]  # core/*.py -> 项目根
        return base / "runtime_state.json"
    except Exception:
        return Path("runtime_state.json").resolve()

def _load_runtime_state() -> dict:
    # 1) 优先用 core.runtime_state（项目统一入口）
    try:
        from core.runtime_state import load_runtime_state
        if callable(load_runtime_state):
            st = load_runtime_state() or {}
            if isinstance(st, dict) and st:
                return st
    except Exception:
        pass

    # 2) 兜底：直接读 runtime_state.json（避免线程/导入问题导致读不到）
    p = _fallback_runtime_state_path()
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
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


    print("🧠 ai_reply(runtime_state) =", st.get("ai_reply"),
          " key=", bool(st.get("ai_api_key")),
          " model=", st.get("ai_model"))

    if not bool(st.get("ai_reply", False)):
        return base


    api_key = str(st.get("ai_api_key") or "").strip()
    model = str(st.get("ai_model") or "").strip()
    if not api_key or not model:
        print("🤖 AI改写：key/model 为空，回退原文")
        return base

    # ✅ 默认值改成你项目里 AI 设置页一致的 host（非常关键）
    host = _cfg_get("AI_API_HOST", "API_HOST", "DPS_API_HOST", default="ai.zhimengai.xyz").strip()
    path = _cfg_get("AI_API_PATH", "API_PATH", "DPS_API_PATH", default="/v1/chat/completions").strip()
    if not path.startswith("/"):
        path = "/" + path

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
        print(f"🤖 AI改写请求：https://{host}{path} model={model} in='{base}'")

        conn = http.client.HTTPSConnection(host, timeout=8)
        conn.request("POST", path,
                     body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                     headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", "ignore")

        if not (200 <= resp.status < 300):
            print(f"🤖 AI改写失败：HTTP {resp.status} raw(head200)={(raw or '')[:200].replace(chr(10),' ')}")
            return base

        data = json.loads(raw) if raw else {}
        txt = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        out = _ensure_punct_and_trim(str(txt), max_chars=max_chars)

        print(f"🤖 AI改写结果：out='{out}'")
        return out or base

    except Exception as e:
        print("🤖 AI改写异常：", e)
        return base

