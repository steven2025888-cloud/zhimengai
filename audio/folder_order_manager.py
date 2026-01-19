import os
import json
import random
from config import AUDIO_BASE_DIR

ORDER_FILE = os.path.join(AUDIO_BASE_DIR, "_folder_order.json")
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")

class FolderOrderManager:
    def __init__(self):
        self.folders: list[str] = []
        self.index = 0
        self.load()

    def scan_folders(self):
        return sorted([
            f for f in os.listdir(AUDIO_BASE_DIR)
            if os.path.isdir(os.path.join(AUDIO_BASE_DIR, f))
        ])

    def load(self):
        all_folders = self.scan_folders()

        if os.path.exists(ORDER_FILE):
            try:
                with open(ORDER_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                # 保留存在的，补新目录
                self.folders = [x for x in saved if x in all_folders]
                for x in all_folders:
                    if x not in self.folders:
                        self.folders.append(x)
            except Exception:
                self.folders = all_folders
        else:
            self.folders = all_folders

        self.index = 0

    def save(self, order: list[str]):
        with open(ORDER_FILE, "w", encoding="utf-8") as f:
            json.dump(order, f, ensure_ascii=False, indent=2)
        self.folders = order
        self.index = 0

    def pick_next_audio(self):
        if not self.folders:
            return None

        folder = self.folders[self.index]
        folder_path = os.path.join(AUDIO_BASE_DIR, folder)

        files = [
            os.path.join(folder_path, f)
            for f in os.listdir(folder_path)
            if f.lower().endswith(AUDIO_EXTS)
        ]

        # 轮到下一个文件夹
        self.index = (self.index + 1) % len(self.folders)

        if not files:
            return self.pick_next_audio()

        return random.choice(files)
