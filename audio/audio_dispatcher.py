# audio/audio_dispatcher.py
import queue
import threading
from dataclasses import dataclass
from typing import Optional, Callable
from core.state import AppState, PlayMode
from audio.audio_player import play_audio_interruptible, play_audio_and_wait
import os
import re
from config import AUDIO_BASE_DIR   # 你之前在 config 里已经定义了

import sounddevice as sd
from audio.audio_picker import pick_by_prefix


@dataclass
class AudioCommand:
    name: str
    path: str

    on_finished: Optional[Callable[[], None]] = None

class AudioDispatcher:
    def __init__(self, state: AppState):
        self.state = state
        self.q: "queue.Queue[AudioCommand]" = queue.Queue()
        self.current_playing = False
        self.stop_event = threading.Event()  # ⭐ 新增：中断信号

        self.resume_random_path: str | None = None
        self.resume_after_priority: bool = False

    def push_report_resume(self, path: str):
        """
        报时：高优先级，但播完要恢复刚才的随机
        - 合成期间不暂停：由 voice_reporter 控制，生成好才调用这里
        """
        print("🕒 报时插播（可恢复）")

        # 如果当前正在播随机：记录下来，等报时完恢复
        if self.current_playing and self.state.play_mode == PlayMode.RANDOM:
            # 注意：这里无法拿到正在播的 path（你现在没存），所以我们需要存一下 current_path（见下）
            self.resume_random_path = getattr(self, "current_path", None)
            self.resume_after_priority = True

        # 打断播放 + 清队列 + 置顶报时
        self.clear()
        self.stop_now()
        self.q.put(AudioCommand(name="PLAY_REPORT", path=path))


    def clear(self) -> None:
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except Exception:
                break

    def push_report(self, path: str):
        """
        报时：最高优先级
        """
        print("🕒 报时插播，打断所有音频")
        self.clear()
        self.stop_now()
        self.q.put(AudioCommand(name="PLAY_REPORT", path=path))

    def push_random(self, path: str) -> None:
        if not self.state.live_ready:
            return
        self.q.put(AudioCommand(name="PLAY_RANDOM", path=path))

    def push_size(self, path: str) -> None:
        if not self.state.live_ready:
            return
        # ⭐ 立刻打断当前播放
        self.stop_event.set()
        # 清队列，把尺寸置顶
        self.clear()
        self.q.put(AudioCommand(name="PLAY_SIZE", path=path))

    def process_once(self) -> None:

        if not self.state.enabled:
            return

        if not self.state.live_ready:  # ⭐ 未进直播间，禁止一切播放
            return

        if self.current_playing:
            return

        try:
            cmd = self.q.get_nowait()
        except queue.Empty:
            return

        if cmd.name == "PLAY_RANDOM" and self.state.play_mode != PlayMode.RANDOM:
            return

        self.current_playing = True
        self.current_path = cmd.path

        try:
            if cmd.name == "PLAY_REPORT":
                print("🕒 播放整点报时：", cmd.path)
                self.state.play_mode = PlayMode.SIZE  # 临时占用
                play_audio_and_wait(cmd.path)
                self.state.play_mode = PlayMode.RANDOM
                print("🔁 报时结束，恢复播放")

            if self.resume_after_priority and self.resume_random_path:
                print("🔁 报时结束，恢复上一段随机：", self.resume_random_path)
                self.resume_after_priority = False
                p = self.resume_random_path
                self.resume_random_path = None
                self.push_random(p)


            elif  cmd.name == "PLAY_SIZE":
                self.state.play_mode = PlayMode.SIZE
                print(f"📌 插播音频：{cmd.path}")

                self.stop_event.clear()

                # ✅ 从随机音频文件名里提取“前缀”
                # 例：尺寸12.wav -> 尺寸
                #     电3.mp3 -> 电
                #     带风机2.wav -> 带风机
                base = os.path.basename(cmd.path)
                m = re.match(r"^(.+?)(\d+)\.", base)
                prefix = m.group(1) if m else os.path.splitext(base)[0]  # 兜底

                # ① 动态固定提示音：<prefix>.wav
                fixed_tip = os.path.join(AUDIO_BASE_DIR, f"{prefix}.wav")

                if os.path.exists(fixed_tip):
                    print("📢 播放固定提示：", fixed_tip)
                    play_audio_and_wait(fixed_tip)
                else:
                    print("ℹ️ 未找到固定提示音：", fixed_tip)

                # ② 播放随机讲解（cmd.path）
                print("🎯 播放随机讲解：", cmd.path)
                play_audio_and_wait(cmd.path)

                # ③ 恢复随机讲解
                self.state.play_mode = PlayMode.RANDOM
                print("🔁 插播结束，恢复随机讲解")




            elif cmd.name == "PLAY_RANDOM":

                print(f"🎲 播放讲解音频：{cmd.path}")

                self.stop_event.clear()

                play_audio_interruptible(cmd.path, self.stop_event)

                # ⭐ 随机播完后，检查是否有待播关注

                if self.state.pending_follow:
                    print("⭐ 插播关注提示音")

                    self.state.pending_follow = False

                    wav = pick_by_prefix("关注")

                    self.push_priority(wav)

                # ② 插播点赞
                if self.state.pending_like:
                    print("👍 插播点赞提示音")
                    self.state.pending_like = False
                    wav = pick_by_prefix("点赞")
                    self.push_priority(wav)
                    return


            if cmd.on_finished:
                cmd.on_finished()
        finally:
            self.current_playing = False

    def stop_now(self):
        print("⛔ 强制停止播放")
        self.stop_event.set()  # ⭐ 加这一行
        sd.stop()
        self.current_playing = False

    def push_priority(self, path: str):
        self.clear()
        self.q.put(AudioCommand(name="PLAY_SIZE", path=path))