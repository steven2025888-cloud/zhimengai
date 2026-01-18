import queue
import threading
import audio_player


class AudioPlayTask:
    def __init__(self, path, on_finished=None):
        self.path = path
        self.on_finished = on_finished


class AudioPlayerThread:
    def __init__(self):
        self.q = queue.Queue()
        self.stop_flag = False
        self.current_task = None

        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while True:
            task: AudioPlayTask = self.q.get()
            if task is None:
                continue

            self.current_task = task
            print(f"🔊 播放音频：{task.path}")

            audio_player.play_audio_and_wait(task.path)

            if task.on_finished:
                task.on_finished()

            self.current_task = None

    def play(self, path, on_finished=None, clear_queue=True):
        """
        播放新音频：
        - 默认清空队列
        - 不杀声卡
        """
        if clear_queue:
            self.clear()

        self.q.put(AudioPlayTask(path, on_finished))

    def clear(self):
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except:
                pass
