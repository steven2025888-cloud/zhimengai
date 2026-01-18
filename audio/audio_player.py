# audio/audio_player.py
import os
import time
import sounddevice as sd
import soundfile as sf
import threading
import numpy as np
import subprocess
GAIN_DB = 3.0
GAIN = 10 ** (GAIN_DB / 20)

def apply_wav_gain(path, data):
    if path.lower().endswith(".wav"):
        print("🔊 WAV音频自动提升 +3dB：", path)
        data = data.astype(np.float32) * GAIN

        max_val = np.max(np.abs(data))
        if max_val > 1.0:
            data = data / max_val
    return data


def play_audio_and_wait(path):
    data, sr = sf.read(path, dtype='float32')
    sd.play(data, sr)
    sd.wait()


def play_audio_interruptible(path: str, stop_event: threading.Event, poll=0.05):
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    data, sr = sf.read(path, dtype='float32')
    data = apply_wav_gain(path, data)

    sd.play(data, sr)

    while True:
        if stop_event.is_set():
            sd.stop()
            return

        stream = sd.get_stream()
        if stream is None or not stream.active:
            return

        time.sleep(poll)
