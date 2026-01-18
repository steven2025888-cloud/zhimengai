from gradio_client import Client, handle_file
import sounddevice as sd
import soundfile as sf
import os
import numpy as np

# Gradio 服务地址
GRADIO_URL = "http://127.0.0.1:7860/"

GAIN_DB = 3.0                 # 提升 3dB
GAIN = 10 ** (GAIN_DB / 20)   # dB 转线性倍率 ≈ 1.414

print("🔥 audio_player.py 已加载（WAV +3dB 版本）")



def play_audio_and_wait(audio_path):
    if not os.path.exists(audio_path):
        print("ERROR: file not found")
        return

    print("🎧 正在播放：", audio_path)

    data, samplerate = sf.read(audio_path, dtype='float32')

    # 只对 wav 提升 3dB
    if audio_path.lower().endswith(".wav"):
        print("🔊 WAV音频自动提升 +3dB：", audio_path)
        data = data * GAIN

        # 防止削波
        max_val = np.max(np.abs(data))
        if max_val > 1.0:
            data = data / max_val

    sd.play(data, samplerate)
    sd.wait()

def on_audio_finished():
    """
    播放完成回调
    """
    print("✅ 音频播放完毕（回调触发）")

def call_index_tts(text: str) -> str:
    print(f"🚀 正在请求 IndexTTS，文本11：{text}")

    client = Client(GRADIO_URL)

    result = client.predict(
        prompt_audio=handle_file(
            "C:/Users/Administrator/Desktop/yinpin/jiangjie.MP3"
        ),
        text=text,
        emo_control="与音色参考音频相同",
        api_name="/tts"
    )

    print(result)

    wav_path=result

    print(f"🎵 语音生成完成：{wav_path}")
    return wav_path


if __name__ == "__main__":
    wav_file = call_index_tts()
    play_audio_and_wait(wav_file)
    on_audio_finished()
