import os
import re
import uuid
from typing import Tuple

import numpy as np
import librosa

# ===== 强制绑定当前目录下的 ffmpeg/bin/ffmpeg.exe =====
import sys
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
FFMPEG_EXE = os.path.join(BASE_DIR, "ffmpeg", "bin", "ffmpeg.exe")

os.environ["FFMPEG_BINARY"] = FFMPEG_EXE
os.environ["PATH"] += os.pathsep + os.path.dirname(FFMPEG_EXE)

from pydub import AudioSegment
AudioSegment.converter = FFMPEG_EXE


def reorder_audio_files(audio_dir: str, supported_exts: Tuple[str, ...]) -> int:
    """
    规则：
    - 同 prefix 的所有音频（不管 wav/mp3/...）统一一个序列
    - 按原数字排序后压缩补齐
    - 同号跨后缀会拆号
    - 两阶段临时名，避免撞名
    """
    if not os.path.exists(audio_dir):
        raise FileNotFoundError(f"音频目录不存在：{audio_dir}")

    exts = tuple(e.lower().lstrip(".") for e in supported_exts)
    pattern = re.compile(r"^(.*?)(\d+)\.([A-Za-z0-9]+)$")

    files = os.listdir(audio_dir)
    groups: dict[str, list[tuple[int, str, str]]] = {}

    for f in files:
        m = pattern.match(f)
        if not m:
            continue
        prefix, num, ext = m.group(1), int(m.group(2)), m.group(3).lower()
        if ext not in exts:
            continue
        groups.setdefault(prefix, []).append((num, f, ext))

    rename_jobs = []

    for prefix, items in groups.items():
        items.sort(key=lambda x: (x[0], x[1].lower()))

        for new_idx, (_, old_name, ext) in enumerate(items, start=1):
            old_path = os.path.join(audio_dir, old_name)
            new_name = f"{prefix}{new_idx}.{ext}"
            new_path = os.path.join(audio_dir, new_name)

            if os.path.abspath(old_path) == os.path.abspath(new_path):
                continue

            tmp_name = f"__tmp__{uuid.uuid4().hex}__{old_name}"
            tmp_path = os.path.join(audio_dir, tmp_name)
            rename_jobs.append((old_path, tmp_path, new_path))

    for old_path, tmp_path, _ in rename_jobs:
        os.rename(old_path, tmp_path)

    renamed = 0
    for _, tmp_path, new_path in rename_jobs:
        os.rename(tmp_path, new_path)
        renamed += 1

    return renamed


def smart_split_audio_to_dir(input_file, output_dir, min_len=30, max_len=300, prefix="讲解"):
    """
    功能：
    - 最短固定 min_len（默认30秒）
    - 最长 max_len（由界面输入）
    - 在每个区间内寻找能量最低谷底切割
    - 输出到 output_dir（即 AUDIO_BASE_DIR = ./audio_assets）
    """
    os.makedirs(output_dir, exist_ok=True)

    print(f"🎧 载入音频：{input_file}")
    y, sr = librosa.load(input_file, sr=None)

    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    db = librosa.amplitude_to_db(rms, ref=np.max)
    times = librosa.frames_to_time(np.arange(len(db)), sr=sr, hop_length=512)

    total_duration = times[-1]
    segments = []
    current_start = 0.0

    while current_start < total_duration:
        target_min = current_start + min_len
        target_max = min(current_start + max_len, total_duration)

        if target_min >= total_duration:
            segments.append((current_start, total_duration))
            break

        idx_range = np.where((times >= target_min) & (times <= target_max))[0]

        if len(idx_range) == 0:
            cut_time = target_max
        else:
            valley_idx = idx_range[np.argmin(db[idx_range])]
            cut_time = times[valley_idx]

        segments.append((current_start, cut_time))
        current_start = cut_time

    audio = AudioSegment.from_file(input_file)

    output_files = []
    for i, (start, end) in enumerate(segments, 1):
        out_name = f"{prefix}{str(i).zfill(2)}.mp3"
        out_path = os.path.join(output_dir, out_name)
        part = audio[start * 1000:end * 1000]
        part.export(out_path, format="mp3")
        output_files.append(out_path)
        print(f"✂️ 生成：{out_name}  时长 {int(end-start)} 秒")

    print(f"✅ 裁剪完成，共生成 {len(output_files)} 段，输出目录：{output_dir}")
    return output_files


def scan_audio_prefixes(audio_dir, exts):
    """
    扫描 前缀+数字 的音频文件，返回所有前缀集合
    例如：炉膛1.wav、炉膛2.mp3 -> {"炉膛"}
    """
    prefixes = set()
    for f in os.listdir(audio_dir):
        name, ext = os.path.splitext(f)
        if ext.lower() not in exts:
            continue
        m = re.match(r"(.+?)(\d+)$", name)
        if m:
            prefixes.add(m.group(1))
    return prefixes
