# audio_player.py
import sys
import sounddevice as sd
import soundfile as sf
import os
import hudie_caiji as hc
def play_audio_and_wait(wav_path):
    if not os.path.exists(wav_path):
        print("ERROR: file not found")
        sys.exit(1)

    data, samplerate = sf.read(wav_path)
    sd.play(data, samplerate)
    sd.wait()

    # 🎯 播放完成，向 stdout 输出信号
    print("AUDIO_FINISHED")
    hc.on_audio_finished()

if __name__ == "__main__":
    wav_path = sys.argv[1]
    play_audio_and_wait(wav_path)
