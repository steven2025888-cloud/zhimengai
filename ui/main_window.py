import os
import sys
import threading
import functools

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QSplitter, QMessageBox, QDialog, QApplication,
    QListWidget, QListWidgetItem, QStackedWidget, QSpinBox, QComboBox,
QCheckBox,  # ✅ 新增
)
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QTextCursor, QIcon

from main import main
from ui.keyword_panel import KeywordPanel
from ui.voice_model_panel import VoiceModelPanel
from ui.switch_toggle import SwitchToggle
from ui.audio_tools_page import AudioToolsPage
from ui.zhuli_keyword_panel import ZhuliKeywordPanel

from core.state import app_state
from api.voice_api import get_machine_code
from config import BASE_URL,AUDIO_BASE_DIR
from ui.anchor_folder_order_panel import AnchorFolderOrderPanel


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

        # 主播音频目录（用户可选，默认 AUDIO_BASE_DIR）

        from core.runtime_state import load_runtime_state


        runtime = load_runtime_state() or {}

        app_state.anchor_audio_dir = str(runtime.get("anchor_audio_dir", str(AUDIO_BASE_DIR)) or str(AUDIO_BASE_DIR))
        try:
            os.makedirs(app_state.anchor_audio_dir, exist_ok=True)
        except Exception:
            app_state.anchor_audio_dir = str(AUDIO_BASE_DIR)



        app_state.enable_voice_report = bool(runtime.get("enable_voice_report", False))
        app_state.enable_danmaku_reply = bool(runtime.get("enable_danmaku_reply", False))
        app_state.enable_auto_reply = bool(runtime.get("enable_auto_reply", False))
        app_state.enable_zhuli = bool(runtime.get("enable_zhuli", True))
        app_state.zhuli_mode = str(runtime.get("zhuli_mode", "A") or "A").upper()


        # ===== 变量调节/音量/语速（按“每段音频”随机目标值 + 平滑过渡） =====
        # ✅ 默认都打开（若 runtime_state.json 没写过开关，则默认 True；写过就尊重写过的值）
        app_state.var_pitch_enabled = bool(runtime.get("var_pitch_enabled", True))
        app_state.var_volume_enabled = bool(runtime.get("var_volume_enabled", True))
        app_state.var_speed_enabled = bool(runtime.get("var_speed_enabled", True))

        # 幅度档位（用字符串存，UI combobox 选择）
        app_state.var_pitch_delta = str(runtime.get("var_pitch_delta", "-5~+5"))
        app_state.var_volume_delta = str(runtime.get("var_volume_delta", "+0~+10"))
        app_state.var_speed_delta = str(runtime.get("var_speed_delta", "+0~+10"))

        # 应用对象：主播/助播/插播/音乐
        app_state.var_apply_anchor = bool(runtime.get("var_apply_anchor", True))
        app_state.var_apply_zhuli  = bool(runtime.get("var_apply_zhuli", True))


        if app_state.zhuli_mode not in ("A", "B"):
            app_state.zhuli_mode = "A"

        self.license_key = license_key
        self.resource_path = resource_path_func
        self.expire_time = expire_time

        self.setWindowTitle("织梦AI直播工具 · 语音调度中控台")
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
        title = QLabel("织梦AI直播工具")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        top.addWidget(title)
        top.addSpacing(10)
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
            "主播设置",
            "关键词设置",
            "助播设置",
            "音色模型",
            "音频工具",

            "DPS设置",
            "回复弹窗",
            "话术改写",
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
            elif name == "主播设置":
                self.stack.addWidget(self._build_anchor_page())
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

    def _build_anchor_page(self) -> QWidget:
        from ui.anchor_folder_order_panel import AnchorFolderOrderPanel

        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        title = QLabel("主播设置")
        title.setStyleSheet("font-size:16px;font-weight:800;")
        desc = QLabel("选择主播音频目录，并设置讲解文件夹轮播顺序")
        desc.setStyleSheet("color:#93A4B7;")

        lay.addWidget(title)
        lay.addWidget(desc)

        panel = AnchorFolderOrderPanel(
            parent=self,
            resource_path_func=self.resource_path,  # 用于 img/*.svg
            save_flag_cb=self._save_runtime_flag  # 用于保存 anchor_audio_dir
        )
        lay.addWidget(panel, 1)


        return page


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

        # ===== 变量调节/音量/语速 卡片（新增）=====
        var_card, var_body = self._make_card("变量调节/音量/语速")

        def _set_enabled(widgets: list, enabled: bool):
            for x in widgets:
                x.setEnabled(bool(enabled))

        def _delta_options(kind: str):
            """每块下拉给 10 个推荐位（含 1 个变态版，方便你压测/测试）。"""
            kind = (kind or "").lower().strip()
            if kind == "pitch":
                return [
                    "-1~+1",
                    "-2~+2",
                    "-3~+3",
                    "-4~+4",
                    "-5~+5",
                    "-6~+6",
                    "-8~+8",
                    "-10~+10",
                    "-12~+12",
                    "-50~+50（变态版）",
                ]
            if kind == "speed":
                return [
                    "-1~+1",
                    "-2~+2",
                    "-3~+3",
                    "-4~+4",
                    "-5~+5",
                    "+0~+5",
                    "+0~+10",
                    "+0~+15",
                    "+0~+20",
                    "+80~+120（变态版）",
                ]
            # volume
            return [
                "+0~+1",
                "+0~+2",
                "+0~+3",
                "+0~+4",
                "+0~+5",
                "+0~+6",
                "+0~+8",
                "+0~+10",
                "+0~+12",
                "+50~+60（变态版）",
            ]

        def _normalize_delta(s: str) -> str:
            # UI 里给 “（变态版）” 这样的显示，但保存时只保存可解析的 "-5~+5" 形式
            s = (s or "").strip()
            if "（" in s:
                s = s.split("（", 1)[0].strip()
            return s

        def _make_var_block(title: str,
                            enabled_attr: str,
                            delta_attr: str,
                            default_delta: str,
                            kind: str):

            wrap = QWidget()
            v = QVBoxLayout(wrap)
            v.setContentsMargins(10, 8, 10, 8)
            v.setSpacing(6)

            # 第一行：开关（不再展示“随机多少秒”，现在是每段音频自动平滑过渡）
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

            # 第二行：下拉幅度
            row2 = QWidget()
            h2 = QHBoxLayout(row2)
            h2.setContentsMargins(0, 0, 0, 0)
            h2.setSpacing(10)

            cmb = QComboBox()
            for opt in _delta_options(kind):
                cmb.addItem(f"设定值基础上 {opt}", _normalize_delta(opt))

            cur = str(getattr(app_state, delta_attr, default_delta) or default_delta)
            idx = cmb.findData(cur)
            cmb.setCurrentIndex(idx if idx >= 0 else 0)

            h2.addWidget(cmb, 1)


            cmb.setFixedHeight(30)


            v.addWidget(row1)
            v.addWidget(row2)

            wrap.setObjectName("VarBlock")
            cb.setObjectName("VarCheck")
            cmb.setObjectName("VarCombo")

            # --- 事件 & 保存 ---
            def _save_enabled(on: bool):
                setattr(app_state, enabled_attr, bool(on))
                # ✅ 直接保存到 runtime_state.json
                self._save_runtime_flag(enabled_attr, bool(on))

            def _save_delta():
                d = cmb.currentData()
                setattr(app_state, delta_attr, d)
                self._save_runtime_flag(delta_attr, d)  # ✅ 直接用 delta_attr

            cb.toggled.connect(_save_enabled)
            cmb.currentIndexChanged.connect(lambda _=None: _save_delta())

            return wrap

        # 三组：变调/变音量/变语速
        var_body.addWidget(_make_var_block(
            "变调节",
            "var_pitch_enabled",
            "var_pitch_delta",
            "-5~+5",
            "pitch",
        ))
        var_body.addWidget(_make_var_block(
            "变音量",
            "var_volume_enabled",
            "var_volume_delta",
            "+0~+10",
            "volume",
        ))
        var_body.addWidget(_make_var_block(
            "变语速",
            "var_speed_enabled",
            "var_speed_delta",
            "+0~+10",
            "speed",
        ))

        # 底部应用对象（主播/助播/插播/音乐）
        targets = QWidget()
        targets.setObjectName("VarTargetsRow")
        th = QHBoxLayout(targets)
        th.setContentsMargins(8, 6, 8, 0)
        th.setSpacing(18)

        chk_anchor = QCheckBox("主播")
        chk_zhuli = QCheckBox("助播")

        chk_anchor.setChecked(bool(getattr(app_state, "var_apply_anchor", True)))
        chk_zhuli.setChecked(bool(getattr(app_state, "var_apply_zhuli", True)))

        def _save_targets():
            app_state.var_apply_anchor = chk_anchor.isChecked()
            app_state.var_apply_zhuli = chk_zhuli.isChecked()
            self._save_runtime_flag("var_apply_anchor", app_state.var_apply_anchor)
            self._save_runtime_flag("var_apply_zhuli", app_state.var_apply_zhuli)

        chk_anchor.toggled.connect(lambda _=None: _save_targets())
        chk_zhuli.toggled.connect(lambda _=None: _save_targets())

        th.addWidget(chk_anchor)
        th.addWidget(chk_zhuli)
        th.addStretch(1)

        var_body.addWidget(targets)

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
        top_row.addWidget(var_card)  # ✅ 新增：在自动化旁边
        top_row.addStretch(1)

        lay.addLayout(top_row)

        splitter = QSplitter(Qt.Horizontal)
        lay.addWidget(splitter, 1)



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

        # 测试
        log_l.addLayout(test_row)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        # 测试
        log_l.addWidget(self.console, 1)
        self.log_stream = LogStream()
        self.log_stream.text_written.connect(self.append_log)

        from logger_bootstrap import SafeTee, log_fp
        sys.stdout = SafeTee(self.log_stream, log_fp)
        sys.stderr = SafeTee(self.log_stream, log_fp)

        splitter.addWidget(log_wrap)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 8)


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

        # ✅ 助播模式（A/B）相关UI与事件已搬到 ZhuliKeywordPanel 内部
        self.zhuli_panel = ZhuliKeywordPanel(self)
        lay.addWidget(self.zhuli_panel, 1)

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
