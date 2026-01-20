import os
import sys
import threading
import functools

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QSplitter, QMessageBox, QDialog, QApplication,
    QListWidget, QListWidgetItem, QStackedWidget, QSpinBox, QComboBox
)
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QTextCursor, QIcon

from main import main
from ui.keyword_panel import KeywordPanel
from ui.voice_model_panel import VoiceModelPanel
from ui.folder_order_panel import FolderOrderPanel
from ui.switch_toggle import SwitchToggle
from ui.audio_tools_page import AudioToolsPage
from ui.zhuli_keyword_panel import ZhuliKeywordPanel

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

        from core.runtime_state import load_runtime_state

        runtime = load_runtime_state() or {}

        app_state.enable_voice_report = bool(runtime.get("enable_voice_report", False))
        app_state.enable_danmaku_reply = bool(runtime.get("enable_danmaku_reply", False))
        app_state.enable_auto_reply = bool(runtime.get("enable_auto_reply", False))
        app_state.enable_zhuli = bool(runtime.get("enable_zhuli", True))
        app_state.zhuli_mode = str(runtime.get("zhuli_mode", "A") or "A").upper()
        if app_state.zhuli_mode not in ("A", "B"):
            app_state.zhuli_mode = "A"

        self.license_key = license_key
        self.resource_path = resource_path_func
        self.expire_time = expire_time

        self.setWindowTitle("AI直播工具 · 语音调度中控台")
        self.setWindowIcon(QIcon(self.resource_path("logo.ico")))
        self.resize(1480, 760)

        self._main_started = False

        # ===== Layout: Left menu + Right stacked pages =====
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self.side = QListWidget()
        self.side.setObjectName("SideMenu")
        self.side.setFixedWidth(170)
        self.side.setSpacing(6)
        root.addWidget(self.side)

        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(12)
        root.addWidget(right, 1)

        # ===== Top title =====
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
        right_l.addLayout(top)

        # ===== Load QSS =====
        qss_path = self.resource_path(os.path.join("ui", "style.qss"))
        if os.path.exists(qss_path):
            with open(qss_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        else:
            print("⚠️ 未找到 style.qss：", qss_path)

        # ===== Stack pages =====
        self.stack = QStackedWidget()
        right_l.addWidget(self.stack, 1)

        # ===== Menu names =====
        self._menu_names = [
            "AI工作台",
            "关键词设置",
            "助播设置",
            "播控设置",
            "DPS设置",
            "回复弹窗",
            "音频工具",
            "话术改写",
            "音色模型",
            "自动切换",
            "评论管理",
            "使用介绍",
        ]
        for name in self._menu_names:
            self.side.addItem(QListWidgetItem(name))

        # ===== Build pages (严格按菜单顺序) =====
        for name in self._menu_names:
            if name == "AI工作台":
                self.stack.addWidget(self._build_workbench_page())
            elif name == "关键词设置":
                self.stack.addWidget(self._build_keyword_page())
            elif name == "助播设置":
                self.stack.addWidget(self._build_zhuli_page())
            elif name == "音频工具":
                self.stack.addWidget(AudioToolsPage(self))
            elif name == "音色模型":
                self.stack.addWidget(self._build_voice_model_page())
            else:
                self.stack.addWidget(self._build_placeholder_page(name))

        self.side.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.side.setCurrentRow(0)

    # =========================
    # Page Builders
    # =========================
    def _build_placeholder_page(self, title: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lab = QLabel(f"{title}（开发中）")
        lab.setAlignment(Qt.AlignCenter)
        lab.setStyleSheet("color:#93A4B7; font-size:14px;")
        lay.addStretch(1)
        lay.addWidget(lab)
        lay.addStretch(1)
        return w

    def _make_card(self, title_text: str) -> tuple[QWidget, QVBoxLayout]:
        frame = QWidget()
        frame.setObjectName("Card")

        v = QVBoxLayout(frame)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        lbl = QLabel(title_text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setObjectName("CardTitle")
        v.addWidget(lbl)

        body = QVBoxLayout()
        body.setSpacing(10)
        v.addLayout(body)

        return frame, body

    def _build_workbench_page(self) -> QWidget:
        from audio import voice_reporter

        BTN_H = 64

        self.btn_start = QPushButton("🚀 启动系统")
        self.btn_start.setFixedSize(160, BTN_H)

        self.btn_clear_log = QPushButton("🧹 清空日志")
        self.btn_clear_log.setFixedSize(140, BTN_H)

        # 报时间隔按钮（单独一行）
        self.btn_report_interval = QPushButton(f"⏱ 报时间隔：{voice_reporter.REPORT_INTERVAL_MINUTES} 分钟")
        self.btn_report_interval.setFixedHeight(32)
        self.btn_report_interval.setMinimumWidth(220)

        # Switch toggles
        self.sw_report = SwitchToggle(checked=app_state.enable_voice_report)
        self.sw_auto_reply = SwitchToggle(checked=app_state.enable_auto_reply)
        self.sw_danmaku_reply = SwitchToggle(checked=app_state.enable_danmaku_reply)
        self.sw_zhuli = SwitchToggle(checked=app_state.enable_zhuli)

        # Cards
        sys_card, sys_body = self._make_card("系统")
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_clear_log)
        row.addStretch(1)
        sys_body.addLayout(row)

        auto_card, auto_body = self._make_card("自动化控制")


        def switch_row(text: str, sw: SwitchToggle) -> QWidget:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(8, 6, 8, 6)
            h.setSpacing(10)
            h.addWidget(QLabel(text))
            h.addStretch(1)
            h.addWidget(sw)
            return w

        def button_row(text: str, btn: QPushButton) -> QWidget:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(8, 6, 8, 6)
            h.setSpacing(10)
            h.addWidget(QLabel(text))
            h.addStretch(1)
            h.addWidget(btn)
            return w

        auto_body.addWidget(switch_row("⏱ 随机报时", self.sw_report))
        auto_body.addWidget(button_row("⏱ 报时间隔", self.btn_report_interval))
        auto_body.addWidget(switch_row("💬 关键词文本回复", self.sw_auto_reply))
        auto_body.addWidget(switch_row("📣 弹幕语音回复", self.sw_danmaku_reply))
        auto_body.addWidget(switch_row("🎧 助播关键词语音", self.sw_zhuli))

        # Workbench layout
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.setSpacing(16)
        top_row.addWidget(sys_card)
        top_row.addWidget(auto_card)
        top_row.addStretch(1)
        lay.addLayout(top_row)

        splitter = QSplitter(Qt.Horizontal)
        lay.addWidget(splitter, 1)

        self.folder_panel = FolderOrderPanel(self)
        try:
            fm = self.folder_panel.manager
            app_state.folder_manager = fm
            print("📂 已注册 folder_manager 到全局 AppState")
        except Exception as e:
            print("⚠️ folder_manager 注入失败：", e)

        splitter.addWidget(self.folder_panel)

        from PySide6.QtWidgets import QLineEdit

        self.test_input = QLineEdit()
        self.test_input.setPlaceholderText("输入一条模拟弹幕，例如：这个多少钱")

        self.btn_test_danmaku = QPushButton("🧪 发送测试弹幕")
        self.btn_test_danmaku.setFixedWidth(140)

        test_row = QHBoxLayout()
        test_row.addWidget(QLabel("本地弹幕测试："))
        test_row.addWidget(self.test_input, 1)
        test_row.addWidget(self.btn_test_danmaku)


        log_wrap = QWidget()



        log_l = QVBoxLayout(log_wrap)
        log_l.setContentsMargins(0, 0, 0, 0)




        self.console = QTextEdit()
        self.console.setReadOnly(True)
        log_l.addWidget(self.console, 1)

        self.log_stream = LogStream()
        self.log_stream.text_written.connect(self.append_log)

        from logger_bootstrap import SafeTee, log_fp
        sys.stdout = SafeTee(self.log_stream, log_fp)
        sys.stderr = SafeTee(self.log_stream, log_fp)

        splitter.addWidget(log_wrap)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 8)

        log_l.addLayout(test_row)
        log_l.addWidget(self.console, 1)

        # Events
        self.btn_start.clicked.connect(self.start_system)
        self.btn_clear_log.clicked.connect(self.clear_log)

        self.btn_report_interval.clicked.connect(self.set_report_interval)

        self.sw_report.toggled.connect(self.toggle_report_switch)
        self.sw_auto_reply.toggled.connect(self.toggle_auto_reply)
        self.sw_danmaku_reply.toggled.connect(self.toggle_danmaku_reply)
        self.sw_zhuli.toggled.connect(self.toggle_zhuli)
        self.btn_test_danmaku.clicked.connect(self.send_test_danmaku)


        return page

    def send_test_danmaku(self):
        text = (self.test_input.text() or "").strip()
        if not text:
            return

        print("🧪 本地模拟弹幕：", text)

        from core.state import app_state

        cb = getattr(app_state, "on_danmaku_cb", None)
        if not cb:
            print("⚠️ 系统尚未启动或未注册回调：请先点【启动系统】")
            return

        try:
            reply = cb("测试用户", text) or ""
            if reply.strip():
                print("🧪 本次命中文本回复：", reply)
        except Exception as e:
            print("❌ 模拟弹幕异常：", e)

        self.test_input.clear()

    def _build_keyword_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        title = QLabel("关键词设置")
        title.setStyleSheet("font-size:16px;font-weight:800;")
        lay.addWidget(title)

        self.keyword_panel = KeywordPanel(self)
        lay.addWidget(self.keyword_panel, 1)
        return page

    def _build_zhuli_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        title = QLabel("助播设置")
        title.setStyleSheet("font-size:16px;font-weight:800;")
        desc = QLabel("配置助播关键词：命中后播放 zhuli_audio 目录对应前缀音频")
        desc.setStyleSheet("color:#93A4B7;")

        lay.addWidget(title)
        lay.addWidget(desc)

        # 模式选择
        mode_row = QWidget()
        hr = QHBoxLayout(mode_row)
        hr.setContentsMargins(0, 0, 0, 0)
        hr.setSpacing(10)
        hr.addWidget(QLabel("优先模式"))
        self.cmb_zhuli_mode = QComboBox()
        self.cmb_zhuli_mode.addItem("模式A（主播关键词优先）", "A")
        self.cmb_zhuli_mode.addItem("模式B（助播关键词优先）", "B")
        # set current
        idx = 0 if app_state.zhuli_mode == "A" else 1
        self.cmb_zhuli_mode.setCurrentIndex(idx)
        hr.addWidget(self.cmb_zhuli_mode)
        hr.addStretch(1)
        self.btn_save_zhuli_mode = QPushButton("💾 保存模式")
        hr.addWidget(self.btn_save_zhuli_mode)
        lay.addWidget(mode_row)

        self.zhuli_panel = ZhuliKeywordPanel(self)
        lay.addWidget(self.zhuli_panel, 1)

        self.btn_save_zhuli_mode.clicked.connect(self.save_zhuli_mode)

        return page

    def _build_voice_model_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        title = QLabel("音色模型")
        title.setStyleSheet("font-size:16px;font-weight:800;")
        desc = QLabel("在这里上传 / 删除 / 设置默认主播音色（支持 MP3 / WAV）")
        desc.setStyleSheet("color:#93A4B7;")

        lay.addWidget(title)
        lay.addWidget(desc)

        panel = VoiceModelPanel(
            base_url=BASE_URL,
            license_key=self.license_key,
            parent=page
        )
        lay.addWidget(panel, 1)
        return page

    # =========================
    # Switch logic + runtime_state
    # =========================
    def _save_runtime_flag(self, key: str, value):
        from core.runtime_state import load_runtime_state, save_runtime_state
        state = load_runtime_state() or {}
        state[key] = value
        save_runtime_state(state)

    def toggle_danmaku_reply(self, checked: bool):
        app_state.enable_danmaku_reply = bool(checked)
        self._save_runtime_flag("enable_danmaku_reply", app_state.enable_danmaku_reply)
        print("📣 弹幕自动回复已开启" if checked else "📣 弹幕自动回复已关闭")

    def toggle_auto_reply(self, checked: bool):
        app_state.enable_auto_reply = bool(checked)
        self._save_runtime_flag("enable_auto_reply", app_state.enable_auto_reply)
        print("💬 关键词自动回复：已开启" if checked else "💬 关键词自动回复：已关闭")

    def toggle_report_switch(self, checked: bool):
        app_state.enable_voice_report = bool(checked)
        self._save_runtime_flag("enable_voice_report", app_state.enable_voice_report)
        print("⏱ 自动语音报时：已开启" if checked else "⏱ 自动语音报时：已关闭")

    def toggle_zhuli(self, checked: bool):
        app_state.enable_zhuli = bool(checked)
        self._save_runtime_flag("enable_zhuli", app_state.enable_zhuli)
        print("🎧 助播关键词语音：已开启" if checked else "🎧 助播关键词语音：已关闭")

    def save_zhuli_mode(self):
        mode = self.cmb_zhuli_mode.currentData()
        if mode not in ("A", "B"):
            mode = "A"
        app_state.zhuli_mode = mode
        self._save_runtime_flag("zhuli_mode", mode)
        QMessageBox.information(self, "保存成功", f"助播模式已保存：{mode}")

    # =========================
    # Report interval
    # =========================
    def set_report_interval(self):
        from audio import voice_reporter

        dlg = QDialog(self)
        dlg.setWindowTitle("⏱ 语音报时间间隔")
        dlg.setFixedSize(320, 170)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(10)

        title = QLabel("设置语音报时间隔（分钟）")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:14px;font-weight:bold;")

        desc = QLabel("最低 5 分钟")
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("color:#666;")

        spin = QSpinBox()
        spin.setRange(1, 60)
        spin.setValue(voice_reporter.REPORT_INTERVAL_MINUTES)
        spin.setSuffix(" 分钟")
        spin.setFixedWidth(160)

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(spin)
        row.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("取消")
        btn_ok = QPushButton("确定")
        btn_ok.setDefault(True)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)

        btn_cancel.clicked.connect(dlg.reject)
        btn_ok.clicked.connect(dlg.accept)

        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addLayout(row)
        layout.addStretch(1)
        layout.addLayout(btn_row)

        if dlg.exec() == QDialog.Accepted:
            val = spin.value()
            if val < 1:
                QMessageBox.warning(self, "时间设置无效", "⏱ 报时间隔不能小于 5 分钟\n\n系统最低限制为 5 分钟。")
                return

            voice_reporter.REPORT_INTERVAL_MINUTES = val
            voice_reporter.save_report_interval(val)
            self.btn_report_interval.setText(f"⏱ 报时间隔：{val} 分钟")
            print(f"⏱ 报时间隔已设置为：{val} 分钟")

    # =========================
    # Logs
    # =========================
    def clear_log(self):
        self.console.clear()
        print("🧹 日志已清空")

    def append_log(self, text: str):
        self.console.moveCursor(QTextCursor.End)
        self.console.insertPlainText(text)
        self.console.ensureCursorVisible()
        self.console.repaint()

    # =========================
    # Start system
    # =========================
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
                    QMessageBox.warning(self, "缺少音色模型", "当前账号尚未上传任何音色模型，请先到【音色模型】页面上传并设置默认。")
                    self._jump_to("音色模型")
                    return

                default_models = [m for m in models if m.get("is_default")]
                if not default_models:
                    app_state.current_model_id = None
                    QMessageBox.warning(self, "未设置默认音色", "请先到【音色模型】页面设置一个默认主播音色。")
                    self._jump_to("音色模型")
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

    def _jump_to(self, menu_name: str):
        try:
            idx = self._menu_names.index(menu_name)
            self.side.setCurrentRow(idx)
        except Exception:
            pass
