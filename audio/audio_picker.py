# audio/audio_picker.py
import os
import random
from config import AUDIO_BASE_DIR, SUPPORTED_AUDIO_EXTS

def pick_by_prefix(prefix: str) -> str:
    """
    从音频目录中随机选一个 prefix+数字 的音频，如：尺寸1.wav、尺寸2.mp3
    排除纯 prefix.wav（例如：尺寸.wav 作为固定提示音）
    """
    if not os.path.exists(AUDIO_BASE_DIR):
        raise FileNotFoundError(f"音频目录不存在: {AUDIO_BASE_DIR}")

    files = [
        f for f in os.listdir(AUDIO_BASE_DIR)
        if f.startswith(prefix)
        and f[len(prefix):].lstrip().split(".")[0].isdigit()   # ⭐ 后面必须是数字
        and f.lower().endswith(SUPPORTED_AUDIO_EXTS)
    ]

    if not files:
        raise RuntimeError(f"未找到任何「{prefix}+数字」音频，如：{prefix}1.wav")

    return os.path.join(AUDIO_BASE_DIR, random.choice(files))
