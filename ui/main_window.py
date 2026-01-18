import os
import sys
import threading
import re
import shutil

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QSplitter, QInputDialog, QMessageBox
)
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QTextCursor, QIcon

from main import main
from ui.keyword_panel import KeywordPanel
from ui.dialogs import confirm_dialog
from core.audio_tools import reorder_audio_files
from audio import voice_reporter
from PySide6.QtWidgets import QInputDialog, QDialogButtonBox

from ui.voice_model_panel import VoiceModelPanel

from core.state import app_state
from api.voice_api import get_machine_code
from config import (
    BASE_URL
)



class LogStream(QObject):
    text_written = Signal(str)

    def write(self, text):
        self.text_written.emit(str(text))

    def flush(self):
        pass


class MainWindow(QWidget):
    def __init__(self, resource_path_func, expire_time: str | None = None, license_key: str = ""):
        super().__init__()

        app_state.license_key = license_key
        app_state.machine_code = get_machine_code()

        self.license_key = license_key

        self.resource_path = resource_path_func

        self.resource_path = resource_path_func
        self.expire_time = expire_time

        self.setWindowTitle("AI直播工具 · 语音调度中控台")
        self.setWindowIcon(QIcon(self.resource_path("logo.ico")))
        self.resize(1480, 760)
        self.setMinimumSize(800, 600)  # 允许缩小
        self.setMaximumSize(16777215, 16777215)  # 解除最大尺寸锁
        self.setWindowState(self.windowState() & ~Qt.WindowMaximized)  # 清除记忆的最大化状态

        self._main_started = False

        qss_path = self.resource_path(os.path.join("ui", "style.qss"))
        if os.path.exists(qss_path):
            with open(qss_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())

        root = QVBoxLayout(self)
        root.setSpacing(12)

        # 顶部标题
        top = QHBoxLayout()
        title = QLabel("AI直播工具")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        sub = QLabel("语音调度系统控制台 · 商用推广版")
        sub.setStyleSheet("color: #93A4B7;")
        top.addWidget(title)
        top.addSpacing(10)
        top.addWidget(sub)
        top.addStretch(1)

        # ✅ 右上角到期时间
        expire_text = self.expire_time or "未知（未获取）"
        self.lbl_expire = QLabel(f"到期时间：{expire_text}")
        self.lbl_expire.setStyleSheet("color:#FFB020; font-weight:700;")
        top.addWidget(self.lbl_expire)

        root.addLayout(top)

        # 按钮条
        row = QHBoxLayout()
        self.btn_start = QPushButton("🚀 启动系统")
        self.btn_reorder_audio = QPushButton("🧹 排序音频")
        self.btn_copy_audio = QPushButton("📁 复制音频")
        self.btn_check_audio = QPushButton("🔍 检查音频")
        self.btn_report_interval = QPushButton(f"⏱ 报时{voice_reporter.REPORT_INTERVAL_MINUTES}分")
        self.btn_clear_log = QPushButton("🧹 清空日志")

        self.btn_split_audio = QPushButton("✂️ 自动裁剪")
        self.btn_split_audio.setFixedSize(110, 60)


        self.btn_clear_log.setFixedHeight(42)

        layout = QHBoxLayout()
        # 按钮之间的间距
        layout.setSpacing(12)

        # 整个区域的左右上下边距
        layout.setContentsMargins(15, 10, 15, 10)

        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_reorder_audio)
        layout.addWidget(self.btn_copy_audio)
        layout.addWidget(self.btn_check_audio)
        layout.addWidget(self.btn_report_interval)
        layout.addWidget(self.btn_clear_log)
        layout.addWidget(self.btn_split_audio)

        row.addStretch(1)


        for b in (
            self.btn_start, self.btn_reorder_audio,
            self.btn_copy_audio, self.btn_check_audio, self.btn_report_interval,self.btn_split_audio
        ):
            b.setFixedSize(110, 60)

        row.addWidget(self.btn_start)
        row.addWidget(self.btn_reorder_audio)
        row.addWidget(self.btn_copy_audio)
        row.addWidget(self.btn_check_audio)
        row.addWidget(self.btn_report_interval)
        row.addWidget(self.btn_split_audio)
        row.addStretch(1)
        root.addLayout(row)

        # 主体
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        left_l.addWidget(self.console, 1)

        splitter.addWidget(left)

        self.keyword_panel = KeywordPanel(self)
        splitter.addWidget(self.keyword_panel)

        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 5)



        self.voice_panel = VoiceModelPanel(
            base_url=BASE_URL,
            license_key=self.license_key
        )
        splitter.addWidget(self.voice_panel)

        # 日志重定向
        self.log_stream = LogStream()
        self.log_stream.text_written.connect(self.append_log)
        sys.stdout = self.log_stream
        sys.stderr = self.log_stream

        # 事件绑定
        self.btn_start.clicked.connect(self.start_system)
        self.btn_reorder_audio.clicked.connect(self.handle_reorder_audio)
        self.btn_copy_audio.clicked.connect(self.handle_copy_audio)
        self.btn_check_audio.clicked.connect(self.handle_check_audio)
        self.btn_report_interval.clicked.connect(self.set_report_interval)
        self.btn_clear_log.clicked.connect(self.clear_log)
        self.btn_split_audio.clicked.connect(self.handle_split_audio)

    def handle_split_audio(self):
        from PySide6.QtWidgets import QFileDialog
        from config import AUDIO_BASE_DIR
        from core.audio_tools import smart_split_audio_to_dir

        # 选择音频
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择需要裁剪的音频",
            "",
            "音频文件 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg)"
        )
        if not file_path:
            return

        # 输入最大时长
        max_sec, ok = QInputDialog.getInt(
            self,
            "设置最长时长",
            "请输入每段最长秒数（最短固定 30 秒）：",
            300,
            30,
            3600
        )
        if not ok:
            return

        print(f"✂️ 开始裁剪：{file_path}")
        print(f"⏱ 最短 30 秒，最长 {max_sec} 秒")
        print(f"📁 输出目录：{AUDIO_BASE_DIR}")

        try:
            files = smart_split_audio_to_dir(
                input_file=file_path,
                output_dir=AUDIO_BASE_DIR,
                min_len=30,
                max_len=max_sec,
                prefix="讲解"
            )

            print("✅ 裁剪完成，生成文件：")
            for f in files:
                print("   ", os.path.basename(f))

            QMessageBox.information(
                self,
                "裁剪完成",
                f"已生成 {len(files)} 段音频\n\n保存目录：\n{AUDIO_BASE_DIR}"
            )

        except Exception as e:
            QMessageBox.critical(self, "裁剪失败", str(e))

    def clear_log(self):
        self.console.clear()
        print("🧹 日志已清空")

    def append_log(self, text: str):
        self.console.moveCursor(QTextCursor.End)
        self.console.insertPlainText(text)
        self.console.ensureCursorVisible()

    def start_system(self):
        if self._main_started:
            return

        # ⭐ 启动前检查音色模型
        from core.state import app_state
        mid = getattr(app_state, "current_model_id", None)
        if not mid or int(mid) <= 0:
            QMessageBox.warning(
                self,
                "需要先设置音色模型",
                "检测到未选择音色模型（model_id 无效）。\n\n请先在右侧【音色模型】面板：\n1）上传/添加音色\n2）设为默认音色\n\n设置完成后再启动系统。"
            )
            return

        self._main_started = True
        self.btn_start.setEnabled(False)

        t = threading.Thread(target=main, args=(self.license_key,), daemon=True)
        t.start()
        print("🚀 系统已启动（后台运行）")

    def handle_reorder_audio(self):
        try:
            from config import AUDIO_BASE_DIR, SUPPORTED_AUDIO_EXTS
            if not confirm_dialog(
                self,
                "确认操作",
                f"将对音频目录进行统一补号排序：\n{AUDIO_BASE_DIR}\n\n确定继续？"
            ):
                return

            renamed = reorder_audio_files(AUDIO_BASE_DIR, SUPPORTED_AUDIO_EXTS)
            print(f"🧹 重新排序完成：重命名 {renamed} 个文件")
        except Exception as e:
            print("❌ 重新排序失败：", e)

    def handle_copy_audio(self):
        from config import AUDIO_BASE_DIR, SUPPORTED_AUDIO_EXTS

        if not os.path.isdir(AUDIO_BASE_DIR):
            QMessageBox.warning(self, "错误", f"音频目录不存在：\n{AUDIO_BASE_DIR}")
            return

        # 1）输入源文件名
        raw_name, ok = QInputDialog.getText(
            self,
            "按序号复制音频",
            "请输入源音频文件名（可不带后缀）：\n例如：烟管165 或 烟管165.mp3"
        )
        if not ok or not raw_name.strip():
            return
        raw_name = raw_name.strip()

        # 2）输入复制数量
        count, ok = QInputDialog.getInt(
            self, "复制数量", "请输入需要生成的份数：", 10, 1, 9999
        )
        if not ok:
            return

        # 3）中文策略选择框
        box = QMessageBox(self)
        box.setWindowTitle("命名冲突处理方式")
        box.setText("如果目标序号已存在，如何处理？")

        btn_auto = box.addButton("自动续号（不覆盖）", QMessageBox.AcceptRole)
        btn_force = box.addButton("强制覆盖原文件", QMessageBox.DestructiveRole)
        btn_cancel = box.addButton("取消操作", QMessageBox.RejectRole)

        box.exec()
        clicked = box.clickedButton()

        if clicked == btn_cancel:
            return
        overwrite = (clicked == btn_force)

        # 4）定位源文件
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
            QMessageBox.warning(self, "未找到源文件",
                                f"未在目录中找到：{base_no_ext} + {SUPPORTED_AUDIO_EXTS}")
            return

        # 5）解析前缀 + 序号
        m = re.match(r"^(.*?)(\d+)$", base_no_ext)
        if not m:
            QMessageBox.warning(
                self,
                "文件名格式不正确",
                "音频文件名必须以数字结尾，例如：烟管165、讲解03"
            )
            return

        prefix = m.group(1)
        num_str = m.group(2)
        width = len(num_str)

        # 6）扫描同前缀最大编号
        pat = re.compile(rf"^{re.escape(prefix)}(\d+){re.escape(suffix)}$", re.IGNORECASE)
        nums = []
        for fn in os.listdir(AUDIO_BASE_DIR):
            mm = pat.match(fn)
            if mm:
                nums.append(int(mm.group(1)))

        start_index = max(nums) + 1 if nums else int(num_str) + 1
        end_index = start_index + count - 1
        width = max(width, len(str(end_index)))

        # 7）开始复制
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

        QMessageBox.information(
            self,
            "复制完成",
            f"源文件：{os.path.basename(src_file)}\n"
            f"生成范围：{prefix}{str(start_index).zfill(width)} ~ {prefix}{str(end_index).zfill(width)}\n\n"
            f"成功生成：{created} 个\n"
            f"跳过：{skipped} 个"
        )

        print(f"📁 音频复制完成：{prefix}{start_index}~{end_index}，生成 {created} 个，跳过 {skipped} 个")

    def handle_check_audio(self):
        try:
            from config import AUDIO_BASE_DIR, SUPPORTED_AUDIO_EXTS
            from core.keyword_io import load_keywords
            from core.audio_tools import scan_audio_prefixes

            keywords = load_keywords()
            keyword_prefixes = set(keywords.keys())
            audio_prefixes = scan_audio_prefixes(AUDIO_BASE_DIR, SUPPORTED_AUDIO_EXTS)

            reserved_prefixes = {"讲解", "关注", "点赞", "下单"}
            audio_prefixes = {p for p in audio_prefixes if p not in reserved_prefixes}

            no_audio = sorted(keyword_prefixes - audio_prefixes)
            no_keyword = sorted(audio_prefixes - keyword_prefixes)
            added = []

            for p in no_keyword:
                keywords[p] = {"priority": 0, "must": [], "any": [], "deny": [], "prefix": p}
                added.append(p)

            if added:
                self.keyword_panel.new_added_prefixes = set(added)
                self.keyword_panel.data = keywords
                self.keyword_panel.refresh_prefix_list()

            msg = []
            if no_audio:
                msg.append("以下分类缺少对应音频：\n" + "、".join(no_audio))
            if added:
                msg.append("检测到新音频前缀：\n" + "、".join(added))
            if not msg:
                msg.append("关键词与音频完全匹配，无需修复。")

            confirm_dialog(self, "检查结果", "\n\n".join(msg))
        except Exception as e:
            confirm_dialog(self, "检查失败", str(e))

    def set_report_interval(self):
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel,
            QSpinBox, QPushButton
        )
        from PySide6.QtCore import Qt

        dlg = QDialog(self)
        dlg.setWindowTitle("⏱ 语音报时间隔")
        dlg.setFixedSize(300, 160)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 15)
        layout.setSpacing(12)

        title = QLabel("设置语音报时间隔")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:14px;font-weight:bold;")

        desc = QLabel("请输入报时间隔（单位：分钟）")
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("color:#666;")

        row = QHBoxLayout()
        spin = QSpinBox()
        spin.setRange(5, 60)  # 最低5分钟
        spin.setValue(voice_reporter.REPORT_INTERVAL_MINUTES)
        spin.setSuffix(" 分钟")
        spin.setFixedWidth(140)

        row.addStretch()
        row.addWidget(spin)
        row.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("color:#000;")
        btn_ok = QPushButton("确定")
        btn_ok.setDefault(True)
        btn_ok.setStyleSheet("color:#000;")


        btn_cancel.clicked.connect(dlg.reject)
        btn_ok.clicked.connect(dlg.accept)

        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)

        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addLayout(row)
        layout.addStretch()
        layout.addLayout(btn_row)

        dlg.setStyleSheet("""
            QDialog {
                background: #FFFFFF;
            }

            QLabel {
                background: transparent;
                color:#000000
            }

            QSpinBox {
                background: #FFFFFF;
                border: 1px solid #D9D9D9;
                color:#000000
                
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
            }

            QPushButton {
                min-width: 70px;
                padding: 6px 12px;
                border-radius: 6px;
                background: #F5F7FA;
            }

            QPushButton:hover {
                background: #E6F0FF;
                color: #000000;
                
            }

            QPushButton:default {
                background-color: #1677FF;
                color: #000000;
            }
        """)

        if dlg.exec() == QDialog.Accepted:
            val = spin.value()
            voice_reporter.REPORT_INTERVAL_MINUTES = val
            voice_reporter.save_report_interval(val)
            self.btn_report_interval.setText(f"⏱ 报时\n{val} 分钟")
            print(f"⏱ 报时间隔已设置为：{val} 分钟")
