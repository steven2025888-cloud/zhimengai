import json
import os

STATE_FILE = "runtime_state.json"

DEFAULT_STATE = {
    "enable_voice_report": False,
    "report_interval_minutes": 15,
    "enable_danmaku_reply": True,   # 📣 弹幕自动回复总开关
    "enable_auto_reply": True       # 💬 文本回复开关
}



def load_runtime_state():
    if not os.path.exists(STATE_FILE):
        return DEFAULT_STATE.copy()
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {**DEFAULT_STATE, **data}  # 缺字段自动补默认
    except:
        return DEFAULT_STATE.copy()

def save_runtime_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
