import os
import re
import shutil

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
    QFileDialog, QSizePolicy
)


from core.audio_tools import reorder_audio_files, smart_split_audio_to_dir, scan_audio_prefixes
from core.keyword_io import load_keywords
from config import AUDIO_BASE_DIR, SUPPORTED_AUDIO_EXTS

from ui.dialogs import confirm_dialog, text_input_dialog, int_input_dialog, choice_dialog, ChoiceItem


class AudioToolsPage(QWidget):
    """音频工具独立页：排序 / 复制 / 检查 / 自动裁剪"""

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        title = QLabel("音频工具")
        title.setStyleSheet("font-size:16px;font-weight:800;")
        sub = QLabel(f"音频目录：{AUDIO_BASE_DIR}")
        sub.setStyleSheet("color:#93A4B7;")
        root.addWidget(title)
        root.addWidget(sub)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.btn_reorder = QPushButton("🧹 排序音频")
        self.btn_copy = QPushButton("📁 复制音频")
        self.btn_check = QPushButton("🔍 检查音频")
        self.btn_split = QPushButton("✂️ 自动裁剪")

        for b in (self.btn_reorder, self.btn_copy, self.btn_check, self.btn_split):
            b.setMinimumSize(140, 38)
            b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

            btn_row.addWidget(b)

        btn_row.addStretch(1)
        root.addLayout(btn_row)
        root.addStretch(1)

        self.btn_reorder.clicked.connect(self.handle_reorder_audio)
        self.btn_copy.clicked.connect(self.handle_copy_audio)
        self.btn_check.clicked.connect(self.handle_check_audio)
        self.btn_split.clicked.connect(self.handle_split_audio)

    # ===================== handlers =====================

    def handle_reorder_audio(self):
        try:
            if not confirm_dialog(
                    self, "确认操作",
                    f"将对音频目录进行统一补号排序：\n{AUDIO_BASE_DIR}\n\n确定继续？"
            ):
                return

            renamed = reorder_audio_files(AUDIO_BASE_DIR, SUPPORTED_AUDIO_EXTS)
            print(f"🧹 重新排序完成：重命名 {renamed} 个文件")

            # ✅ 统一弹窗风格
            confirm_dialog(self, "完成", f"已重命名 {renamed} 个文件")
        except Exception as e:
            confirm_dialog(self, "失败", str(e))

    def handle_copy_audio(self):
        if not os.path.isdir(AUDIO_BASE_DIR):
            confirm_dialog(self, "错误", f"音频目录不存在：\n{AUDIO_BASE_DIR}")
            return

        raw_name, ok = text_input_dialog(
            self,
            "按序号复制音频",
            "请输入源音频文件名（可不带后缀）：\n例如：烟管165 或 烟管165.mp3",
            placeholder="例如：烟管165"
        )
        if not ok or not raw_name.strip():
            return
        raw_name = raw_name.strip()

        count, ok = int_input_dialog(
            self, "复制数量", "请输入需要生成的份数：",
            value=10, min_value=1, max_value=9999
        )
        if not ok:
            return

        choice, ok = choice_dialog(
            self,
            "命名冲突处理方式",
            "如果目标序号已存在，如何处理？",
            items=[
                ChoiceItem("自动续号（不覆盖）", role="normal"),
                ChoiceItem("强制覆盖原文件", role="destructive"),
                ChoiceItem("取消操作", role="cancel"),
            ],
        )
        if not ok or choice == "取消操作":
            return
        overwrite = (choice == "强制覆盖原文件")

        base_no_ext = os.path.splitext(raw_name)[0]
        src_file = None
        suffix = None

        for ext in SUPPORTED_AUDIO_EXTS:
            p = os.path.join(AUDIO_BASE_DIR, base_no_ext + ext)
            if os.path.exists(p):
                src_file = p
                suffix = ext
                break

        if not src_file:
            confirm_dialog(self, "未找到源文件", f"未在目录中找到：{base_no_ext} + {SUPPORTED_AUDIO_EXTS}")
            return

        m = re.match(r"^(.*?)(\d+)$", base_no_ext)
        if not m:
            confirm_dialog(self, "文件名格式不正确", "音频文件名必须以数字结尾，例如：烟管165、讲解03")
            return

        prefix = m.group(1)
        num_str = m.group(2)
        width = len(num_str)

        pat = re.compile(rf"^{re.escape(prefix)}(\d+){re.escape(suffix)}$", re.IGNORECASE)
        nums = []
        for fn in os.listdir(AUDIO_BASE_DIR):
            mm = pat.match(fn)
            if mm:
                nums.append(int(mm.group(1)))

        start_index = max(nums) + 1 if nums else int(num_str) + 1
        end_index = start_index + count - 1
        width = max(width, len(str(end_index)))

        created, skipped = 0, 0
        for n in range(start_index, start_index + count):
            n_str = str(n).zfill(width)
            dst_name = f"{prefix}{n_str}{suffix}"
            dst_path = os.path.join(AUDIO_BASE_DIR, dst_name)

            if os.path.exists(dst_path) and not overwrite:
                skipped += 1
                continue

            shutil.copy2(src_file, dst_path)
            created += 1

        confirm_dialog(self, "复制完成", f"已生成 {created} 份\n跳过 {skipped} 份\n\n目录：\n{AUDIO_BASE_DIR}")

        print(f"📁 音频复制完成：{prefix}{start_index}~{end_index}，生成 {created} 个，跳过 {skipped} 个")

    def handle_check_audio(self):
        try:
            keywords = load_keywords()
            keyword_prefixes = set(keywords.keys())
            audio_prefixes = scan_audio_prefixes(AUDIO_BASE_DIR, SUPPORTED_AUDIO_EXTS)

            reserved_prefixes = {"讲解", "关注", "点赞", "下单"}
            audio_prefixes = {p for p in audio_prefixes if p not in reserved_prefixes}

            no_audio = sorted(keyword_prefixes - audio_prefixes)
            no_keyword = sorted(audio_prefixes - keyword_prefixes)

            msg = []
            if no_audio:
                msg.append("以下分类缺少对应音频：\n" + "、".join(no_audio))
            if no_keyword:
                msg.append("检测到新音频前缀（关键词未配置）：\n" + "、".join(no_keyword))
            if not msg:
                msg.append("关键词与音频前缀完全匹配，无需修复。")

            confirm_dialog(self, "检查结果", "\n\n".join(msg))
        except Exception as e:
            confirm_dialog(self, "检查失败", str(e))

    def handle_split_audio(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择需要裁剪的音频", "",
            "音频文件 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg)"
        )
        if not file_path:
            return

        max_sec, ok = int_input_dialog(
            self,
            "设置最长时长（秒）",
            "请输入每段最长秒数（范围 5~300 秒）：",
            value=60,
            min_value=5,
            max_value=300,
            step=1
        )
        if not ok:
            return

        try:
            files = smart_split_audio_to_dir(
                input_file=file_path,
                output_dir=AUDIO_BASE_DIR,
                min_len=5,
                max_len=max_sec,
                prefix="讲解"
            )
            confirm_dialog(self, "裁剪完成", f"已生成 {len(files)} 段音频\n\n保存目录：\n{AUDIO_BASE_DIR}")
        except Exception as e:
            confirm_dialog(self, "裁剪失败", str(e))

