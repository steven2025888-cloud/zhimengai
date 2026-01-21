# ui/page_workbench.py
import sys
import threading
import functools

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
    QSplitter, QMessageBox, QDialog, QSpinBox, QLineEdit
)
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QTextCursor

from core.state import app_state
from api.voice_api import get_machine_code
from config import BASE_URL
from ui.switch_toggle import SwitchToggle

print = functools.partial(print, flush=True)


class LogStream(QObject):
    text_written = Signal(str)

    def write(self, text):
        if text:
            self.text_written.emit(str(text))

    def flush(self):
        pass


class WorkbenchPage(QWidget):
    _stdout_hooked = False

    def __init__(self, ctx: dict):
        super().__init__()
        self.ctx = ctx
        self._main_started = False

        from audio import voice_reporter

        BTN_H = 64

        # ===== buttons / switches =====
        self.btn_start = QPushButton("🚀 启动系统")
        self.btn_start.setFixedSize(160, BTN_H)

        self.btn_clear_log = QPushButton("🧹 清空日志")
        self.btn_clear_log.setFixedSize(140, BTN_H)

        self.btn_report_interval = QPushButton(f"⏱ 报时间隔：{voice_reporter.REPORT_INTERVAL_MINUTES} 分钟")
        self.btn_report_interval.setFixedHeight(32)
        self.btn_report_interval.setMinimumWidth(220)

        self.sw_report = SwitchToggle(checked=app_state.enable_voice_report)
        self.sw_auto_reply = SwitchToggle(checked=app_state.enable_auto_reply)
        self.sw_danmaku_reply = SwitchToggle(checked=app_state.enable_danmaku_reply)
        self.sw_zhuli = SwitchToggle(checked=app_state.enable_zhuli)

        # ===== layout =====
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        sys_card = self._make_sys_card()
        auto_card = self._make_auto_card()
        var_card = self._make_var_card()

        top_row.addWidget(sys_card)
        top_row.addWidget(auto_card)
        top_row.addWidget(var_card)
        top_row.addStretch(1)
        lay.addLayout(top_row)

        splitter = QSplitter(Qt.Horizontal)
        lay.addWidget(splitter, 1)

        # ===== test row + console =====
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
        log_l.addLayout(test_row)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        log_l.addWidget(self.console, 1)

        splitter.addWidget(log_wrap)
        splitter.setStretchFactor(0, 8)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(page, 1)

        # ===== hook stdout once =====
        self._hook_stdout()

        # ===== events =====
        self.btn_start.clicked.connect(self.start_system)
        self.btn_clear_log.clicked.connect(self.clear_log)
        self.btn_report_interval.clicked.connect(self.set_report_interval)

        self.sw_report.toggled.connect(self.toggle_report_switch)
        self.sw_auto_reply.toggled.connect(self.toggle_auto_reply)
        self.sw_danmaku_reply.toggled.connect(self.toggle_danmaku_reply)
        self.sw_zhuli.toggled.connect(self.toggle_zhuli)
        self.btn_test_danmaku.clicked.connect(self.send_test_danmaku)

    # ---------------- UI blocks ----------------
    def _make_card(self, title_text: str):
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

    def _make_sys_card(self):
        sys_card, sys_body = self._make_card("系统")
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_clear_log)
        row.addStretch(1)
        sys_body.addLayout(row)
        return sys_card

    def _make_auto_card(self):
        auto_card, auto_body = self._make_card("自动化控制")

        auto_body.addWidget(self._switch_row("⏱ 随机报时", self.sw_report))
        auto_body.addWidget(self._button_row("⏱ 报时间隔", self.btn_report_interval))
        auto_body.addWidget(self._switch_row("💬 关键词文本回复", self.sw_auto_reply))
        auto_body.addWidget(self._switch_row("📣 弹幕语音回复", self.sw_danmaku_reply))
        auto_body.addWidget(self._switch_row("🎧 助播关键词语音", self.sw_zhuli))

        return auto_card

    def _make_var_card(self):
        # 变量调节区域：保留你原逻辑（每段音频随机一个目标值并平滑过渡）
        var_card, var_body = self._make_card("变量调节/音量/语速")

        from PySide6.QtWidgets import QCheckBox, QComboBox, QWidget, QVBoxLayout, QHBoxLayout

        def _delta_options(kind: str):
            kind = (kind or "").lower().strip()
            if kind == "pitch":
                return ["-1~+1", "-2~+2", "-3~+3", "-4~+4", "-5~+5", "-6~+6", "-8~+8", "-10~+10", "-12~+12", "-50~+50（变态版）"]
            if kind == "speed":
                return ["-1~+1", "-2~+2", "-3~+3", "-4~+4", "-5~+5", "+0~+5", "+0~+10", "+0~+15", "+0~+20", "+80~+120（变态版）"]
            return ["+0~+1", "+0~+2", "+0~+3", "+0~+4", "+0~+5", "+0~+6", "+0~+8", "+0~+10", "+0~+12", "+50~+60（变态版）"]

        def _normalize_delta(s: str) -> str:
            s = (s or "").strip()
            if "（" in s:
                s = s.split("（", 1)[0].strip()
            return s

        def _make_var_block(title: str, enabled_attr: str, delta_attr: str, default_delta: str, kind: str):
            wrap = QWidget()
            v = QVBoxLayout(wrap)
            v.setContentsMargins(10, 8, 10, 8)
            v.setSpacing(6)

            row1 = QWidget()
            h1 = QHBoxLayout(row1)
            h1.setContentsMargins(0, 0, 0, 0)
            h1.setSpacing(10)

            cb = QCheckBox(title)
            cb.setChecked(bool(getattr(app_state, enabled_attr, True)))
            tip = QLabel("每段音频随机一个目标值，并在本段内平滑过渡")
            tip.setStyleSheet("color:#93A4B7;")

            h1.addWidget(cb)
            h1.addWidget(tip)
            h1.addStretch(1)

            row2 = QWidget()
            h2 = QHBoxLayout(row2)
            h2.setContentsMargins(0, 0, 0, 0)
            h2.setSpacing(10)

            cmb = QComboBox()
            for opt in _delta_options(kind):
                cmb.addItem(f"设定值基础上 {opt}", _normalize_delta(opt))
            cur = str(getattr(app_state, delta_attr, default_delta) or default_delta)
            idx = cmb.findData(c
