import os
import numpy as np
import librosa

# ===== 路径配置 =====
FFMPEG_EXE = r"C:\Users\111\Desktop\ffmpeg-8.0.1\bin\ffmpeg.exe"
INPUT_FILE = r"C:\Users\111\Desktop\chuli\input.mp3"
OUTPUT_DIR = r"C:\Users\111\Desktop\chuli\output"

# 绑定 ffmpeg 给 pydub
os.environ["FFMPEG_BINARY"] = FFMPEG_EXE
os.environ["PATH"] += os.pathsep + os.path.dirname(FFMPEG_EXE)

from pydub import AudioSegment
AudioSegment.converter = FFMPEG_EXE

# ===== 参数 =====
MIN_LEN = 60       # 最短 1 分钟
MAX_LEN = 300      # 最长 5 分钟

os.makedirs(OUTPUT_DIR, exist_ok=True)

print("🎧 读取音频并计算能量...")
y, sr = librosa.load(INPUT_FILE, sr=None)

# 计算 RMS 能量
rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
db = librosa.amplitude_to_db(rms, ref=np.max)
times = librosa.frames_to_time(np.arange(len(db)), sr=sr, hop_length=512)

total_duration = times[-1]
print(f"⏱ 音频总时长：{int(total_duration)} 秒")

print("✂️ 使用能量谷底强制切割（1~5分钟，始终在最低处切）")

segments = []
current_start = 0.0

while current_start < total_duration:
    target_min = current_start + MIN_LEN
    target_max = min(current_start + MAX_LEN, total_duration)

    if target_min >= total_duration:
        segments.append((current_start, total_duration))
        break

    # 找这个区间内的帧
    idx_range = np.where((times >= target_min) & (times <= target_max))[0]

    if len(idx_range) == 0:
        segments.append((current_start, target_max))
        current_start = target_max
        continue

    # 找最低能量谷底
    valley_idx = idx_range[np.argmin(db[idx_range])]
    cut_time = times[valley_idx]

    segments.append((current_start, cut_time))
    current_start = cut_time

print(f"📌 共切成 {len(segments)} 段")

# ===== 导出 MP3 =====
audio = AudioSegment.from_mp3(INPUT_FILE)

for idx, (start, end) in enumerate(segments, 1):
    part = audio[start * 1000:end * 1000]
    name = f"讲解{idx:02d}.mp3"
    out_path = os.path.join(OUTPUT_DIR, name)
    part.export(out_path, format="mp3")
    print(f"✅ 导出 {name}  时长 {int(end - start)} 秒")

print("\n🎉 处理完成！输出目录：", OUTPUT_DIR)
