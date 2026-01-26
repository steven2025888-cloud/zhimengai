# audio/audio_player.py
# 基于你的原版改造：增加“真正暂停/续播”（从暂停位置继续）+ 提供 dispatcher 需要的 set_paused / stop_playback 接口
import os
import time
import threading
from typing import Optional

import sounddevice as sd
import soundfile as sf
import numpy as np


def play_audio_and_wait(path: str):
    """保持原有行为：一次性播放直到结束。"""
    data, sr = sf.read(path, dtype="float32")
    sd.play(data, sr)
    sd.wait()


def _ensure_2d(data: np.ndarray) -> np.ndarray:
    """sounddevice OutputStream 回调更喜欢 (frames, channels)"""
    if data.ndim == 1:
        return data.reshape(-1, 1)
    return data


# ===================== 全局控制（用于 dispatcher import）=====================
# 注意：项目里通常只会同时播放一条音频，因此用全局控制即可。
# 若未来要并发播放，可改为“播放器实例化”方案。
_global_pause_event = threading.Event()
_global_lock = threading.Lock()
_current_stop_event: Optional[threading.Event] = None
_current_pause_event: Optional[threading.Event] = None


def set_paused(paused: bool):
    """供外部（dispatcher/UI）控制暂停/恢复。
    paused=True：暂停（输出静音，不推进播放指针）
    paused=False：恢复（从暂停位置继续）
    """
    with _global_lock:
        pe = _current_pause_event or _global_pause_event

    if paused:
        pe.set()
    else:
        pe.clear()


def stop_playback():
    """供外部强制停止当前播放。"""
    with _global_lock:
        se = _current_stop_event

    if se is not None:
        se.set()
    # 兜底：如果某些情况下没注册 stop_event，也尽力停掉 sounddevice
    try:
        sd.stop()
    except Exception:
        pass


def play_audio_interruptible(
    path: str,
    stop_event: threading.Event,
    poll: float = 0.02,
    pause_event: Optional[threading.Event] = None,
):
    """可中断播放（并可选支持暂停/恢复，且从暂停位置继续）。

    - stop_event.set(): 立刻停止播放并返回
    - pause_event.set(): 暂停（输出静音，不推进播放指针）
    - pause_event.clear(): 恢复（从暂停处继续播）

    兼容旧 dispatcher：如果 pause_event=None，则使用模块级全局 pause_event，
    并允许外部调用 set_paused()/stop_playback() 控制本次播放。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    # 选择 pause_event：优先使用调用方传入；否则使用全局
    pe = pause_event if pause_event is not None else _global_pause_event

    # 注册本次播放的控制句柄（供 set_paused/stop_playback 使用）
    global _current_stop_event, _current_pause_event
    with _global_lock:
        _current_stop_event = stop_event
        _current_pause_event = pe

    data, sr = sf.read(path, dtype="float32")
    data = _ensure_2d(data)

    # 如需增益：启用这行即可
    # data = apply_wav_gain(path, data)

    frames_total = int(data.shape[0])
    channels = int(data.shape[1])

    idx_lock = threading.Lock()
    idx = 0
    finished = threading.Event()

    def callback(outdata, frames, time_info, status):
        nonlocal idx
        if stop_event.is_set():
            outdata.fill(0)
            raise sd.CallbackStop

        # 暂停：输出静音，但不推进 idx
        if pe.is_set():
            outdata.fill(0)
            return

        with idx_lock:
            start = idx
            end = min(idx + frames, frames_total)
            chunk = data[start:end]
            idx = end

        outdata.fill(0)
        if chunk.size:
            outdata[: chunk.shape[0], : channels] = chunk

        if end >= frames_total:
            finished.set()
            raise sd.CallbackStop

    stream = sd.OutputStream(
        samplerate=sr,
        channels=channels,
        dtype="float32",
        callback=callback,
        finished_callback=lambda: finished.set(),
    )

    try:
        stream.start()
        while True:
            if stop_event.is_set():
                try:
                    stream.stop()
                except Exception:
                    pass
                return

            if finished.is_set():
                return

            if not stream.active:
                return

            time.sleep(poll)
    finally:
        try:
            stream.close()
        except Exception:
            pass
        # 清理当前控制句柄
        with _global_lock:
            if _current_stop_event is stop_event:
                _current_stop_event = None
            if _current_pause_event is pe:
                _current_pause_event = None
