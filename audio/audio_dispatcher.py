# audio/audio_dispatcher.py
import os
import random
import threading
from dataclasses import dataclass
from typing import Optional, Callable
from collections import deque

import sounddevice as sd

from core.state import AppState
from audio.audio_player import play_audio_interruptible, play_audio_and_wait


PLAY_REPORT = "PLAY_REPORT"
# 为了兼容你现有调用：主播关键词仍叫 PLAY_SIZE
PLAY_ANCHOR = "PLAY_SIZE"
PLAY_ZHULI = "PLAY_ZHULI"
PLAY_RANDOM = "PLAY_RANDOM"


@dataclass
class AudioCommand:
    name: str
    path: str
    on_finished: Optional[Callable[[], None]] = None


class AudioDispatcher:
    def __init__(self, state: AppState):
        self.state = state

        # 优先级队列：报时 > (主播关键词/助播关键词 按模式决定) > 轮播
        self.report_q: deque[AudioCommand] = deque()
        self.anchor_q: deque[AudioCommand] = deque()
        self.zhuli_q: deque[AudioCommand] = deque()
        self.random_q: deque[AudioCommand] = deque()

        self.current_playing = False
        self.current_name: str | None = None
        self.current_path: str | None = None

        # stop_event：用于可中断播放（轮播一定用；关键词/报时靠 sd.stop 也能停）
        self.stop_event = threading.Event()

        # 被打断的轮播，等高优先级都播完再恢复
        self.resume_after_high: str | None = None

        self._lock = threading.RLock()

        # 文件夹轮播控制
        self.folder_cycle_thread: threading.Thread | None = None
        self.folder_cycle_running = False

    # ===================== 辅助状态 =====================

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self.report_q or self.anchor_q or self.zhuli_q or self.random_q)

    def is_idle(self) -> bool:
        return (not self.current_playing) and (not self.has_pending())

    # ===================== 文件夹顺序轮播 =====================

    def start_folder_cycle(self):
        if self.folder_cycle_running:
            return
        self.folder_cycle_running = True
        self.folder_cycle_thread = threading.Thread(target=self._folder_cycle_loop, daemon=True)
        self.folder_cycle_thread.start()
        print("🔁 已启动文件夹顺序轮播线程")

    def _get_ordered_folders_compatible(self):
        fm = getattr(self.state, "folder_manager", None)
        if not fm:
            return []
        if hasattr(fm, "get_ordered_folders"):
            try:
                return fm.get_ordered_folders()
            except Exception:
                return []
        for attr in ("ordered_folders", "folders", "folder_list"):
            if hasattr(fm, attr):
                folders = getattr(fm, attr)
                if isinstance(folders, list):
                    return folders
        return []

    def _scan_folder_audio(self, folder):
        try:
            folder_p = folder if hasattr(folder, "iterdir") else None
            if folder_p is None:
                from pathlib import Path
                folder_p = Path(folder)
        except Exception:
            return []

        return [
            str(p)
            for p in folder_p.iterdir()
            if p.is_file() and p.suffix.lower() in (".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg")
        ]

    def _folder_cycle_loop(self):
        while True:
            if not self.state.enabled or not self.state.live_ready:
                threading.Event().wait(1)
                continue

            folders = self._get_ordered_folders_compatible()
            if not folders:
                threading.Event().wait(1)
                continue

            for folder in folders:
                if not self.state.enabled or not self.state.live_ready:
                    break

                try:
                    audio_files = self._scan_folder_audio(folder)
                except Exception:
                    continue
                if not audio_files:
                    continue

                wav = random.choice(audio_files)
                folder_name = getattr(folder, "name", str(folder))
                print(f"📂 文件夹轮播：{folder_name} -> {os.path.basename(wav)}")
                self.push_random(wav)

                # 等当前播放完（关键词/报时会让 current_playing 一直 True，避免轮播抢跑）
                while self.current_playing and self.state.enabled and self.state.live_ready:
                    threading.Event().wait(0.3)

    # ===================== 入队接口（优先级策略） =====================

    def push_random(self, path: str):
        if not self.state.live_ready:
            return
        with self._lock:
            self.random_q.append(AudioCommand(name=PLAY_RANDOM, path=path))

    def push_anchor_keyword(self, path: str):
        """主播关键词（原 push_size）"""
        if not self.state.live_ready:
            return
        with self._lock:
            # 报时/关键词/助播 在播：不打断，只排队
            if self.current_playing and self.current_name in (PLAY_REPORT, PLAY_ANCHOR, PLAY_ZHULI):
                print("📌 主播关键词：当前是报时/关键词，改为排队 ->", os.path.basename(path))
                self.anchor_q.append(AudioCommand(name=PLAY_ANCHOR, path=path))
                return

            # 当前是轮播：打断轮播并记住恢复点
            if self.current_playing and self.current_name == PLAY_RANDOM:
                if self.current_path:
                    self.resume_after_high = self.current_path
                print("📌 主播关键词（打断轮播）->", os.path.basename(path))
                self.stop_now()
                self.random_q.clear()
                self.anchor_q.append(AudioCommand(name=PLAY_ANCHOR, path=path))
                return

            # 空闲：直接播
            print("📌 主播关键词（空闲直接播）->", os.path.basename(path))
            self.anchor_q.append(AudioCommand(name=PLAY_ANCHOR, path=path))



    def push_zhuli_keyword(self, path: str):
        """助播关键词"""
        if not self.state.live_ready:
            return
        with self._lock:
            if self.current_playing and self.current_name in (PLAY_REPORT, PLAY_ANCHOR, PLAY_ZHULI):
                print("📌 助播关键词：当前是报时/关键词，改为排队 ->", os.path.basename(path))
                self.zhuli_q.append(AudioCommand(name=PLAY_ZHULI, path=path))
                return

            if self.current_playing and self.current_name == PLAY_RANDOM:
                if self.current_path:
                    self.resume_after_high = self.current_path
                print("📌 助播关键词（打断轮播）->", os.path.basename(path))
                self.stop_now()
                self.random_q.clear()
                self.zhuli_q.append(AudioCommand(name=PLAY_ZHULI, path=path))
                return

            print("📌 助播关键词（空闲直接播）->", os.path.basename(path))
            self.zhuli_q.append(AudioCommand(name=PLAY_ZHULI, path=path))

    def push_report(self, report_path: str):
        """报时插播（最高优先级）：打断轮播/关键词/助播，并恢复被打断的关键词/助播。"""
        if not self.state.live_ready:
            return

        with self._lock:
            # 1) 如果当前在播：先把“被打断的那条”放回队列最前（保证报时后能接着播）
            if self.current_playing and self.current_path and self.current_name:
                # 被打断的是主播关键词：回到主播队列最前
                if self.current_name == PLAY_ANCHOR:
                    self.anchor_q.appendleft(AudioCommand(name=PLAY_ANCHOR, path=self.current_path))
                    print("↩️ 关键词被报时打断，已回队列最前 ->", os.path.basename(self.current_path))

                # 被打断的是助播关键词：回到助播队列最前
                elif self.current_name == PLAY_ZHULI:
                    self.zhuli_q.appendleft(AudioCommand(name=PLAY_ZHULI, path=self.current_path))
                    print("↩️ 助播关键词被报时打断，已回队列最前 ->", os.path.basename(self.current_path))

                # 被打断的是轮播：记录恢复点（你原来的逻辑）
                elif self.current_name == PLAY_RANDOM:
                    self.resume_after_high = self.current_path

            # 2) 打断一切（轮播/关键词/助播）
            if self.current_playing and self.current_name in (PLAY_RANDOM, PLAY_ANCHOR, PLAY_ZHULI):
                print("🕒 报时插播（打断一切）->", os.path.basename(report_path))
                self.stop_now()
                self.random_q.clear()

            # 3) 报时置顶（永远最先播）
            self.report_q.appendleft(AudioCommand(name=PLAY_REPORT, path=report_path))

    # 兼容 voice_reporter 旧调用
    def push_report_resume(self, report_path: str):
        # 兼容 voice_reporter 旧调用
        return self.push_report(report_path)

    def clear_all(self):
        with self._lock:
            self.report_q.clear()
            self.anchor_q.clear()
            self.zhuli_q.clear()
            self.random_q.clear()

    # ===================== 播放调度主循环 =====================

    def _pick_next_high(self) -> Optional[AudioCommand]:
        """根据模式A/B 决定主播关键词与助播关键词的先后。"""
        mode = str(getattr(self.state, "zhuli_mode", "A") or "A").upper()

        if mode == "B":
            # 模式B：报时 > 助播关键词 > 主播关键词 > 轮播
            if self.zhuli_q:
                return self.zhuli_q.popleft()
            if self.anchor_q:
                return self.anchor_q.popleft()
            return None

        # 默认模式A：报时 > 主播关键词 > 助播关键词 > 轮播
        if self.anchor_q:
            return self.anchor_q.popleft()
        if self.zhuli_q:
            return self.zhuli_q.popleft()
        return None

    def process_once(self):
        if not self.state.enabled or not self.state.live_ready:
            return
        if self.current_playing:
            return

        with self._lock:
            cmd: Optional[AudioCommand] = None

            # 1) 报时最高
            if self.report_q:
                cmd = self.report_q.popleft()
            else:
                # 2) 主播/助播按模式优先
                cmd = self._pick_next_high()

            # 3) 高优先级都空了：如果有被打断的轮播，先恢复它
            if cmd is None:
                if self.resume_after_high:
                    self.random_q.appendleft(AudioCommand(name=PLAY_RANDOM, path=self.resume_after_high))
                    self.resume_after_high = None
                if self.random_q:
                    cmd = self.random_q.popleft()

            if cmd is None:
                return

            self.current_playing = True
            self.current_name = cmd.name
            self.current_path = cmd.path

        try:
            if cmd.name == PLAY_REPORT:
                print("🕒 播放整点报时：", cmd.path)
                play_audio_and_wait(cmd.path)

            elif cmd.name in (PLAY_ANCHOR, PLAY_ZHULI):
                tag = "主播关键词" if cmd.name == PLAY_ANCHOR else "助播关键词"
                print(f"🎯 播放{tag}插播：", cmd.path)
                play_audio_and_wait(cmd.path)

            elif cmd.name == PLAY_RANDOM:
                print("🎲 播放轮播音频：", cmd.path)
                self.stop_event.clear()
                play_audio_interruptible(cmd.path, self.stop_event)

            if cmd.on_finished:
                cmd.on_finished()

        finally:
            with self._lock:
                self.current_playing = False
                self.current_name = None
                self.current_path = None

    # ===================== 强制中断 =====================

    def stop_now(self):
        """只发停止信号 + sd.stop()，不要把 current_playing 置 False。"""
        print("⛔ 强制停止播放")
        self.stop_event.set()
        try:
            sd.stop()
        except Exception:
            pass
