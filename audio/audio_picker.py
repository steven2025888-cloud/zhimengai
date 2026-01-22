# audio/audio_picker.py
import os
import random
from core.state import app_state
from config import KEYWORDS_BASE_DIR, SUPPORTED_AUDIO_EXTS


def _get_anchor_dir() -> str:
    d = str(KEYWORDS_BASE_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def pick_by_prefix(prefix: str) -> str:
    """
    从主播音频目录中随机选一个 prefix+数字 的音频，如：尺寸1.wav、尺寸2.mp3
    排除纯 prefix.wav（例如：尺寸.wav 作为固定提示音）
    """
    base_dir = _get_anchor_dir()

    if not os.path.exists(base_dir):
        raise FileNotFoundError(f"音频目录不存在: {base_dir}")

    files = [
        f for f in os.listdir(base_dir)
        if f.startswith(prefix)
        and f[len(prefix):].lstrip().split(".")[0].isdigit()
        and f.lower().endswith(SUPPORTED_AUDIO_EXTS)
    ]

    if not files:
        raise RuntimeError(f"未找到任何「{prefix}+数字」音频，如：{prefix}1.wav（目录：{base_dir}）")

    return os.path.join(base_dir, random.choice(files))
