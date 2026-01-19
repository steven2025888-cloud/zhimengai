
# main_window.py (Fixed)
# - Uses VoiceModelPanel in a dialog for model management (MP3/WAV)
# - Removes any references to non-existent VoiceModelLoader UI
# - Removes undefined btn_upload_model
# - Keeps existing features: start, audio tools, automation switches, logs, FolderOrderPanel, KeywordPanel
# - Cleaned imports and stable signal bindings

import os
import sys
import threading
import re
import shutil
import functools

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QSplitter, QInputDialog, QMessageBox, QDialog, QApplication
)
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QTextCursor, QIcon

from main import main
from ui.keyword_panel import KeywordPanel
from ui.dialogs import confirm_dialog
from core.audio_tools import reorder_audio_files
from audio import voice_reporter
from ui.voice_model_panel import VoiceModelPanel
from ui.folder_order_panel import FolderOrderPanel

from core.state import app_state
from api.voice_api import get_machine_code
from config import BASE_URL

print = functools.partial(print, flush=True)


class LogStream(QObject):
    text_written = Signal(str)

    def write(self, text):
        if text:
            self.text_written.emit(str(text))
            QApplication.processEvents()

    def flush(self):
        pass


class MainWindow(QWidget):
    def __init__(self, resource_path_func, expire_time: str | None = None, license_key: str = ""):
        super().__init__()

        from core.runtime_state import load_runtime_state, save_runtime_state

        runtime = load_runtime_state()

        app_state.enable_voice_report = runtime.get("enable_voice_report", False)
        app_state.enable_danmaku_reply = runtime.get("enable_danmaku_reply", False)
        app_state.enable_auto_reply = runtime.get("enable_auto_reply", False)

        self.license_key = license_key
        self.resource_path = resource_path_func
        self.expire_time = expire_time

        self.setWindowTitle("AI直播工具 · 语音调度中控台")
        self.setWindowIcon(QIcon(self.resource_path("logo.ico")))
        self.resize(1480, 760)

        self._main_started = False

        root = QVBoxLayout(self)
        root.setSpacing(12)

        # ===== 顶部标题 =====
        top = QHBoxLayout()
        title = QLabel("AI直播工具")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        sub = QLabel("语音调度系统控制台 · 商用推广版")
        sub.setStyleSheet("color: #93A4B7;")
        top.addWidget(title)
        top.addSpacing(10)
        top.addWidget(sub)
        top.addStretch(1)

        expire_text = self.expire_time or "未知"
        self.lbl_expire = QLabel(f"到期时间：{expire_text}")
        self.lbl_expire.setStyleSheet("color:#FFB020; font-weight:700;")
        top.addWidget(self.lbl_expire)

        root.addLayout(top)

        # ===== 创建所有按钮 =====
        BTN_W, BTN_H = 110, 64
        SW_W, SW_H = 130, 64

        self.btn_start = QPushButton("🚀 启动系统")

        self.btn_reorder_audio = QPushButton("🧹 排序音频")
        self.btn_copy_audio = QPushButton("📁 复制音频")
        self.btn_check_audio = QPushButton("🔍 检查音频")
        self.btn_split_audio = QPushButton("✂️ 自动裁剪")
        self.btn_clear_log = QPushButton("🧹 清空日志")

        # 音色模型（弹窗）
        self.btn_voice_model = QPushButton("🎤 音色模型")
        self.btn_voice_model.setFixedSize(120, 64)

        self.btn_report_interval = QPushButton(f"⏱ 间隔\n{voice_reporter.REPORT_INTERVAL_MINUTES} 分")

        self.btn_report_switch = QPushButton()
        self.btn_report_switch.setCheckable(True)
        self.btn_report_switch.setChecked(app_state.enable_voice_report)

        self.btn_auto_reply = QPushButton()
        self.btn_auto_reply.setCheckable(True)
        self.btn_auto_reply.setChecked(app_state.enable_auto_reply)

        self.btn_danmaku_reply = QPushButton()
        self.btn_danmaku_reply.setCheckable(True)
        self.btn_danmaku_reply.setChecked(app_state.enable_danmaku_reply)

        # ===== 开关样式函数 =====
        def set_switch_style(btn, title, enabled):
            btn.setFixedSize(SW_W, SW_H)
            btn.setText(f"{title}\n{'已开启' if enabled else '已关闭'}")
            btn.setStyleSheet(f"""
                QPushButton {{
                    border-radius: 8px;
                    font-weight: 700;
                    background: {"#E6FFFB" if enabled else "#FFF1F0"};
                    color: {"#08979C" if enabled else "#CF1322"};
                }}
            """)

        set_switch_style(self.btn_report_switch, "⏱ 报时", app_state.enable_voice_report)
        set_switch_style(self.btn_auto_reply, "💬 文本回复", app_state.enable_auto_reply)
        set_switch_style(self.btn_danmaku_reply, "📣 语音回复", app_state.enable_danmaku_reply)

        # ===== 分组容器 =====
        def make_group(title):
            frame = QWidget()
            frame.setStyleSheet("""
                QWidget {
                    border: 1px solid rgba(255,255,255,0.9);
                    border-radius: 10px;
                    background: transparent;
                }
            """)

            v = QVBoxLayout(frame)
            v.setContentsMargins(10, 10, 10, 10)
            v.setSpacing(8)

            lbl = QLabel(title)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("font-weight:800;color:#ffffff;")
            v.addWidget(lbl)

            row = QHBoxLayout()
            row.setSpacing(8)
            v.addLayout(row)

            return frame, row

        # 系统组
        sys_box, sys_row = make_group("系统")
        self.btn_start.setFixedSize(120, BTN_H)
        sys_row.addWidget(self.btn_start)
        sys_row.addWidget(self.btn_voice_model)

        # 音频工具组
        audio_box, audio_row = make_group("音频工具")
        for b in (self.btn_reorder_audio, self.btn_copy_audio, self.btn_check_audio, self.btn_split_audio,
                  self.btn_clear_log):
            b.setFixedSize(BTN_W, BTN_H)
            audio_row.addWidget(b)

        # 自动化控制组
        auto_box, auto_row = make_group("自动化控制")
        self.btn_report_interval.setFixedSize(120, SW_H)
        auto_row.addWidget(self.btn_report_switch)
        auto_row.addWidget(self.btn_report_interval)
        auto_row.addWidget(self.btn_auto_reply)
        auto_row.addWidget(self.btn_danmaku_reply)

        # 载入全局主题 QSS
        qss_path = self.resource_path(os.path.join("ui", "style.qss"))
        if os.path.exists(qss_path):
            with open(qss_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        else:
            print("⚠️ 未找到 style.qss：", qss_path)

        # 总布局
        panel_row = QHBoxLayout()
        panel_row.setSpacing(16)
        panel_row.addWidget(sys_box)
        panel_row.addWidget(audio_box)
        panel_row.addWidget(auto_box)
        panel_row.addStretch(1)

        root.addLayout(panel_row)

        # ===== 主体区域（FolderOrderPanel + 日志 + 关键词） =====
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        self.folder_panel = FolderOrderPanel(self)
        splitter.addWidget(self.folder_panel)

        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        left_l.addWidget(self.console, 1)

        self.log_stream = LogStream()
        self.log_stream.text_written.connect(self.append_log)

        from logger_bootstrap import SafeTee, log_fp
        sys.stdout = SafeTee(self.log_stream, log_fp)
        sys.stderr = SafeTee(self.log_stream, log_fp)

        splitter.addWidget(left)

        self.keyword_panel = KeywordPanel(self)
        splitter.addWidget(self.keyword_panel)

        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 5)

        # ===== 事件绑定 =====
        self.btn_start.clicked.connect(self.start_system)
        self.btn_reorder_audio.clicked.connect(self.handle_reorder_audio)
        self.btn_copy_audio.clicked.connect(self.handle_copy_audio)
        self.btn_check_audio.clicked.connect(self.handle_check_audio)
        self.btn_split_audio.clicked.connect(self.handle_split_audio)
        self.btn_clear_log.clicked.connect(self.clear_log)

        self.btn_report_switch.clicked.connect(self.toggle_report_switch)
        self.btn_auto_reply.toggled.connect(self.toggle_auto_reply)
        self.btn_danmaku_reply.toggled.connect(self.toggle_danmaku_reply)
        self.btn_report_interval.clicked.connect(self.set_report_interval)
        self.btn_voice_model.clicked.connect(self.open_voice_model_dialog)

    # ===== 弹窗：音色模型管理（VoiceModelPanel） =====
    def open_voice_model_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("主播音色模型管理（支持 MP3 / WAV）")
        dlg.setFixedSize(520, 680)

        layout = QVBoxLayout(dlg)
        panel = VoiceModelPanel(
            base_url=BASE_URL,
            license_key=self.license_key,
            parent=dlg
        )
        layout.addWidget(panel)

        dlg.exec()

    # ===== 通用样式方法 =====
    def set_switch_style(self, btn, title, enabled):
        btn.setFixedSize(130, 64)
        btn.setText(f"{title}\n{'已开启' if enabled else '已关闭'}")
        btn.setStyleSheet(f"""
            QPushButton {{
                border-radius: 8px;
                font-weight: 700;
                background: {"#E6FFFB" if enabled else "#FFF1F0"};
                color: {"#08979C" if enabled else "#CF1322"};
            }}
        """)

    # ===== 开关逻辑 =====
    def toggle_danmaku_reply(self, checked: bool):
        from core.runtime_state import load_runtime_state, save_runtime_state
        app_state.enable_danmaku_reply = bool(checked)
        state = load_runtime_state()
        state["enable_danmaku_reply"] = app_state.enable_danmaku_reply
        save_runtime_state(state)
        self.set_switch_style(self.btn_danmaku_reply, "📣 语音回复", checked)
        print("📣 弹幕自动回复已开启" if checked else "📣 弹幕自动回复已关闭")

    def toggle_auto_reply(self, checked: bool):
        from core.runtime_state import load_runtime_state, save_runtime_state
        app_state.enable_auto_reply = bool(checked)
        state = load_runtime_state()
        state["enable_auto_reply"] = app_state.enable_auto_reply
        save_runtime_state(state)
        self.set_switch_style(self.btn_auto_reply, "💬 文本回复", checked)
        print("💬 关键词自动回复：已开启" if checked else "💬 关键词自动回复：已关闭")

    def toggle_report_switch(self):
        from core.runtime_state import save_runtime_state, load_runtime_state
        enabled = self.btn_report_switch.isChecked()
        app_state.enable_voice_report = enabled
        state = load_runtime_state()
        state["enable_voice_report"] = enabled
        save_runtime_state(state)
        self.set_switch_style(self.btn_report_switch, "⏱ 报时", enabled)
        print("⏱ 自动语音报时：已开启" if enabled else "⏱ 自动语音报时：已关闭")

    # ===== 音频裁剪 =====
    def handle_split_audio(self):
        from PySide6.QtWidgets import QFileDialog
        from config import AUDIO_BASE_DIR
        from core.audio_tools import smart_split_audio_to_dir

        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择需要裁剪的音频", "",
            "音频文件 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg)"
        )
        if not file_path:
            return

        max_min, ok = QInputDialog.getDouble(
            self, "设置最长时长（分钟）", "请输入每段最长分钟数（最短 0.5 分钟）：",
            3.0, 0.5, 60.0, 1
        )
        if not ok:
            return

        max_sec = int(max_min * 60)

        print(f"✂️ AI开始裁剪：{file_path}")
        print(f"⏱ 最短 0.5 分钟，最长 {max_min} 分钟")
        print(f"📁 输出目录：{AUDIO_BASE_DIR}")

        try:
            files = smart_split_audio_to_dir(
                input_file=file_path,
                output_dir=AUDIO_BASE_DIR,
                min_len=30,
                max_len=max_sec,
                prefix="讲解"
            )

            print("✅ AI裁剪完成，生成文件：")
            for f in files:
                print("   ", os.path.basename(f))

            QMessageBox.information(self, "裁剪完成",
                                    f"已生成 {len(files)} 段音频\n\n保存目录：\n{AUDIO_BASE_DIR}")
        except Exception as e:
            QMessageBox.critical(self, "裁剪失败", str(e))

    # ===== 日志 =====
    def clear_log(self):
        self.console.clear()
        print("🧹 日志已清空")

    def append_log(self, text: str):
        self.console.moveCursor(QTextCursor.End)
        self.console.insertPlainText(text)
        self.console.ensureCursorVisible()
        self.console.repaint()

    # ===== 启动系统 =====
    def start_system(self):
        if self._main_started:
            return

        from api.voice_api import VoiceApiClient

        app_state.license_key = self.license_key
        app_state.machine_code = get_machine_code()

        if app_state.enable_voice_report or app_state.enable_danmaku_reply:
            try:
                client = VoiceApiClient(BASE_URL, self.license_key)
                resp = client.list_models()

                if not isinstance(resp, dict) or resp.get("code") != 0:
                    QMessageBox.critical(self, "启动失败", f"无法获取云端音色列表：\n{resp}")
                    return

                models = resp.get("data", [])
                if not models:
                    app_state.current_model_id = None
                    QMessageBox.warning(self, "缺少音色模型", "当前账号尚未上传任何音色模型，请先添加并设置默认。")
                    self.show_voice_model_setup_dialog()
                    return

                default_models = [m for m in models if m.get("is_default")]
                if not default_models:
                    app_state.current_model_id = None
                    QMessageBox.warning(self, "未设置默认音色", "请先在音色库中设置一个默认主播音色。")
                    self.show_voice_model_setup_dialog()
                    return

                app_state.current_model_id = int(default_models[0]["id"])

            except Exception as e:
                QMessageBox.critical(self, "启动校验失败", f"音色服务器连接失败：\n{e}")
                return

        self._main_started = True
        self.btn_start.setEnabled(False)

        t = threading.Thread(target=main, args=(self.license_key,), daemon=True)
        t.start()
        print("🚀 系统已启动（后台运行）")

    # ===== 首次配置引导 =====
    def show_voice_model_setup_dialog(self):
        from PySide6.QtWidgets import QVBoxLayout, QLabel, QPushButton

        dlg = QDialog(self)
        dlg.setWindowTitle("首次使用语音功能 - 音色配置")
        dlg.setFixedSize(1000, 800)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("🎤 尚未配置默认主播音色")
        title.setStyleSheet("font-size:18px;font-weight:800;")

        desc = QLabel(
            "你已开启【语音报时 / 弹幕语音回复】功能，\n"
            "但当前系统中还没有可用的默认音色模型。\n\n"
            "请先完成以下步骤：\n"
            "1. 添加一个主播音色模型\n"
            "2. 设置为默认音色\n\n"
            "配置完成后即可启动系统。"
        )
        desc.setStyleSheet("color:#666; line-height:22px;")

        panel = VoiceModelPanel(
            base_url=BASE_URL,
            license_key=self.license_key
        )
        panel.setMinimumHeight(220)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_ok = QPushButton("已完成配置，继续启动")
        btn_ok.setFixedHeight(36)

        def check_and_close():
            mid = getattr(app_state, "current_model_id", None)
            if not mid or int(mid) <= 0:
                QMessageBox.warning(dlg, "未完成配置", "请先设置一个默认音色模型。")
                return
            dlg.accept()
            self.start_system()

        btn_ok.clicked.connect(check_and_close)

        btn_row.addWidget(btn_ok)

        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addWidget(panel, 1)
        layout.addLayout(btn_row)

        dlg.exec()

    # ===== 音频排序 =====
    def handle_reorder_audio(self):
        try:
            from config import AUDIO_BASE_DIR, SUPPORTED_AUDIO_EXTS
            if not confirm_dialog(self, "确认操作",
                                  f"将对音频目录进行统一补号排序：\n{AUDIO_BASE_DIR}\n\n确定继续？"):
                return

            renamed = reorder_audio_files(AUDIO_BASE_DIR, SUPPORTED_AUDIO_EXTS)
            print(f"🧹 重新排序完成：重命名 {renamed} 个文件")
        except Exception as e:
            print("❌ 重新排序失败：", e)

    # ===== 音频复制 =====
    def handle_copy_audio(self):
        from config import AUDIO_BASE_DIR, SUPPORTED_AUDIO_EXTS

        if not os.path.isdir(AUDIO_BASE_DIR):
            QMessageBox.warning(self, "错误", f"音频目录不存在：\n{AUDIO_BASE_DIR}")
            return

        raw_name, ok = QInputDialog.getText(
            self, "按序号复制音频",
            "请输入源音频文件名（可不带后缀）：\n例如：烟管165 或 烟管165.mp3"
        )
        if not ok or not raw_name.strip():
            return
        raw_name = raw_name.strip()

        count, ok = QInputDialog.getInt(self, "复制数量", "请输入需要生成的份数：", 10, 1, 9999)
        if not ok:
            return

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

        m = re.match(r"^(.*?)(\d+)$", base_no_ext)
        if not m:
            QMessageBox.warning(self, "文件名格式不正确",
                                "音频文件名必须以数字结尾，例如：烟管165、讲解03")
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

        QMessageBox.information(
            self, "复制完成",
            f"源文件：{os.path.basename(src_file)}\n"
            f"生成范围：{prefix}{str(start_index).zfill(width)} ~ {prefix}{str(end_index).zfill(width)}\n\n"
            f"成功生成：{created} 个\n"
            f"跳过：{skipped} 个"
        )

        print(f"📁 音频复制完成：{prefix}{start_index}~{end_index}，生成 {created} 个，跳过 {skipped} 个")

    # ===== 音频检查 =====
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

    # ===== 报时间隔 =====
    def set_report_interval(self):
        from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QPushButton

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
        spin.setRange(1, 60)
        spin.setValue(voice_reporter.REPORT_INTERVAL_MINUTES)
        spin.setSuffix(" 分钟")
        spin.setFixedWidth(140)

        row.addStretch()
        row.addWidget(spin)
        row.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton("取消")
        btn_ok = QPushButton("确定")
        btn_ok.setDefault(True)

        btn_cancel.clicked.connect(dlg.reject)
        btn_ok.clicked.connect(dlg.accept)

        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)

        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addLayout(row)
        layout.addStretch()
        layout.addLayout(btn_row)

        if dlg.exec() == QDialog.Accepted:
            val = spin.value()

            if val < 5:
                QMessageBox.warning(
                    self, "时间设置无效",
                    "⏱ 报时间隔不能小于 5 分钟\n\n系统最低限制为 5 分钟。"
                )
                return

            voice_reporter.REPORT_INTERVAL_MINUTES = val
            voice_reporter.save_report_interval(val)
            self.btn_report_interval.setText(f"⏱ 报时\n{val} 分钟")
            print(f"⏱ 报时间隔已设置为：{val} 分钟")
