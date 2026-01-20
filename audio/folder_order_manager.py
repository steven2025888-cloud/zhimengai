# audio/folder_order_manager.py
import os
import json
import random
from typing import Optional

from config import AUDIO_BASE_DIR

AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")


class FolderOrderManager:
    """
    讲解文件夹顺序管理器（支持可切换 base_dir）
    - base_dir 默认 AUDIO_BASE_DIR
    - 顺序文件保存在：{base_dir}/_folder_order.json
    """

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = os.path.abspath(str(base_dir or AUDIO_BASE_DIR))
        os.makedirs(self.base_dir, exist_ok=True)

        self.folders: list[str] = []
        self.index = 0
        self.load()

    def set_base_dir(self, base_dir: str):
        self.base_dir = os.path.abspath(str(base_dir))
        os.makedirs(self.base_dir, exist_ok=True)
        self.load()

    @property
    def order_file(self) -> str:
        return os.path.join(self.base_dir, "_folder_order.json")

    def scan_folders(self) -> list[str]:
        if not os.path.isdir(self.base_dir):
            return []
        return sorted([
            f for f in os.listdir(self.base_dir)
            if os.path.isdir(os.path.join(self.base_dir, f))
        ])

    def load(self):
        all_folders = self.scan_folders()

        if os.path.exists(self.order_file):
            try:
                with open(self.order_file, "r", encoding="utf-8") as f:
                    saved = json.load(f) or []
                # 保留存在的 + 补新目录
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
        with open(self.order_file, "w", encoding="utf-8") as f:
            json.dump(order, f, ensure_ascii=False, indent=2)
        self.folders = order[:]
        self.index = 0

    def pick_next_audio(self) -> Optional[str]:
        """
        按文件夹顺序轮播：每次从当前文件夹随机挑一个音频
        """
        if not self.folders:
            return None

        if self.index < 0 or self.index >= len(self.folders):
            self.index = 0

        tried = 0
        while tried < len(self.folders):
            folder = self.folders[self.index]
            folder_path = os.path.join(self.base_dir, folder)

            # 下一个文件夹
            self.index = (self.index + 1) % len(self.folders)
            tried += 1

            if not os.path.isdir(folder_path):
                continue

            try:
                files = [
                    os.path.join(folder_path, fn)
                    for fn in os.listdir(folder_path)
                    if fn.lower().endswith(AUDIO_EXTS)
                ]
            except FileNotFoundError:
                continue

            if files:
                return random.choice(files)

        return None
