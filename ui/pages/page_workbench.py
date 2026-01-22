# ui/page_workbench.py
import sys
import threading
import functools



from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
    QSplitter, QDialog, QSpinBox, QLineEdit, QGridLayout, QApplication
)
from ui.dialogs import confirm_dialog

from PySide6.QtCore import Qt, QObject, Signal, QProcess
from PySide6.QtGui import QTextCursor

from core.state import app_state
from api.voice_api import get_machine_code
from config import BASE_URL
from ui.switch_toggle import SwitchToggle
from PySide6.QtCore import QProcess
import os
import webbrowser



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


        # ===== buttons / switches =====
        BTN_H = 38

        # ===== 系统区 6 个按钮（两排三列）=====
        def _mk_btn(text: str, primary: bool = False) -> QPushButton:
            b = QPushButton(text)
            from PySide6.QtWidgets import QSizePolicy

            b.setMinimumHeight(BTN_H)  # 只限制最小高度
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)  # 允许纵向/横向拉伸填满

            b.setMinimumWidth(150)
            if primary:
                b.setStyleSheet("""
                    QPushButton{
                        background:#2D8CF0;color:#fff;border:none;border-radius:10px;
                        padding:6px 14px;font-weight:800;
                    }
                    QPushButton:disabled{opacity:0.55;}
                """)
            else:
                b.setStyleSheet("""
                    QPushButton{
                        background:rgba(255,255,255,0.06);
                        border:1px solid rgba(255,255,255,0.10);
                        border-radius:10px;
                        padding:6px 14px;
                        font-weight:700;
                    }
                    QPushButton:hover{background:rgba(255,255,255,0.10);}
                """)
            return b

        self.btn_start = _mk_btn("🚀 启动系统", primary=True)
        self.btn_restart = _mk_btn("🔄 重新运行")
        self.btn_check_update = _mk_btn("⬆️ 检查更新")

        self.btn_doc = _mk_btn("📖 说明文档")
        self.btn_open_folder = _mk_btn("📂 打开目录")
        self.btn_clear_log = _mk_btn("🧹 清空日志")

        # 其他区域按钮（你原来就有）
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
        self.test_input.setPlaceholderText("输入一条模拟弹幕，例如：测试")
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

        self.btn_restart.clicked.connect(self.restart_app)
        self.btn_check_update.clicked.connect(self.check_update)
        self.btn_doc.clicked.connect(self.open_doc)
        self.btn_open_folder.clicked.connect(self.open_app_folder)

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

        # ✅ 标题固定高度（两张卡：自动化控制 / 变量调节... 会立刻对齐）
        TITLE_H = 34  # 你想更高就改这里：32/34/36 都行
        lbl.setFixedHeight(TITLE_H)

        # 可选：避免标题被挤压时换行导致高度异常
        lbl.setWordWrap(False)

        v.addWidget(lbl)

        body = QVBoxLayout()
        body.setSpacing(10)
        v.addLayout(body)
        return frame, body

    def open_app_folder(self):
        # 优先用 config.get_app_dir()，没有就退化到 exe 同级
        try:
            from config import get_app_dir
            p = str(get_app_dir())
        except Exception:
            p = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()

        try:
            os.startfile(p)  # Windows
        except Exception:
            try:
                webbrowser.open("file:///" + p.replace("\\", "/"))
            except Exception:
                confirm_dialog(self, "目录", p)

    def _make_sys_card(self):
        from PySide6.QtWidgets import QSizePolicy

        frame = QWidget()
        frame.setObjectName("Card")
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        v = QVBoxLayout(frame)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        # 两列三排
        grid.addWidget(self.btn_start, 0, 0)
        grid.addWidget(self.btn_restart, 0, 1)

        grid.addWidget(self.btn_check_update, 1, 0)
        grid.addWidget(self.btn_doc, 1, 1)

        grid.addWidget(self.btn_open_folder, 2, 0)
        grid.addWidget(self.btn_clear_log, 2, 1)

        # 让网格“撑满”
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        grid.setRowStretch(2, 1)

        v.addLayout(grid, 1)  # 关键：给 grid 一个 stretch，让它吃满垂直空间
        return frame

    def restart_app(self):
        from ui.dialogs import confirm_dialog  # 按你的真实路径改

        if not confirm_dialog(self, "重新运行", "确定要重新启动软件吗？"):
            return

        try:
            # frozen: 直接重启 exe；非 frozen: 重启 python + 脚本
            if getattr(sys, "frozen", False):
                ok = QProcess.startDetached(sys.executable, sys.argv[1:], os.getcwd())
            else:
                ok = QProcess.startDetached(sys.executable, sys.argv, os.getcwd())

            if not ok:
                confirm_dialog(self, "失败", "重新运行失败：无法启动新进程")
                return
        except Exception as e:
            confirm_dialog(self, "异常", f"重新运行异常：\n{e}")
            return

        # 退出当前进程
        from PySide6.QtWidgets import QApplication
        QApplication.quit()
        sys.exit(0)

    def check_update(self):
        # 你已经有“强制检查更新并在需要时退出”的逻辑，直接复用
        # 对应这个文件里的函数：force_check_update_and_exit_if_needed :contentReference[oaicite:2]{index=2}
        try:
            from core.updater import force_check_update_and_exit_if_needed
        except Exception:
            # 如果你文件名不是 update_checker.py，就把这里改成你的真实模块名
            confirm_dialog(self, "未找到更新模块",
                           "没找到更新检查模块：请确认 core/updater.py 是否存在并包含 force_check_update_and_exit_if_needed。")

            return

        force_check_update_and_exit_if_needed()

    def open_doc(self):
        try:
            from config import DOC_URL
        except Exception:
            confirm_dialog(self, "缺少配置", "config.py 里还没有 DOC_URL，请先加上。")
            return

        url = (DOC_URL or "").strip()
        if not url:
            confirm_dialog(self, "说明文档", "说明文档地址未配置，请在 config.py 设置 DOC_URL。")

            return

        webbrowser.open(url)


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

        from PySide6.QtWidgets import QSpinBox


        def _delta_options(kind: str):
            kind = (kind or "").lower().strip()
            if kind == "pitch":
                return ["-1~+1", "-2~+2", "-3~+3", "-4~+4", "-5~+5", "-6~+6", "-8~+8", "-10~+10", "-12~+12"]
            if kind == "speed":
                return ["-1~+1", "-2~+2", "-3~+3", "-4~+4", "-5~+5", "+0~+5", "+0~+10", "+0~+15", "+0~+20"]
            return ["+0~+1", "+0~+2", "+0~+3", "+0~+4", "+0~+5", "+0~+6", "+0~+8", "+0~+10", "+0~+12"]

        def _normalize_delta(s: str) -> str:
            s = (s or "").strip()
            if "（" in s:
                s = s.split("（", 1)[0].strip()
            return s

        def _make_var_block(title: str, enabled_attr: str, delta_attr: str, default_delta: str, kind: str,
                            minsec_attr: str, default_minsec: int):
            wrap = QWidget()
            wrap.setObjectName("VarBlock")
            v = QVBoxLayout(wrap)
            v.setContentsMargins(10, 8, 10, 8)
            v.setSpacing(6)

            row1 = QWidget()
            h1 = QHBoxLayout(row1)
            h1.setContentsMargins(0, 0, 0, 0)
            h1.setSpacing(10)

            cb = QCheckBox(title)
            cb.setChecked(bool(getattr(app_state, enabled_attr, True)))

            h1.addWidget(cb)
            h1.addStretch(1)

            row2 = QWidget()
            h2 = QHBoxLayout(row2)
            h2.setContentsMargins(0, 0, 0, 0)
            h2.setSpacing(10)

            cmb = QComboBox()
            cmb.setObjectName("VarCombo")
            for opt in _delta_options(kind):
                cmb.addItem(f"设定值基础上 {opt}", _normalize_delta(opt))
            cur = str(getattr(app_state, delta_attr, default_delta) or default_delta)
            idx = cmb.findData(cur)
            cmb.setCurrentIndex(idx if idx >= 0 else 0)
            cmb.setFixedHeight(30)

            h2.addWidget(cmb, 1)

            v.addWidget(row1)
            v.addWidget(row2)

            # 短音频保护：少于 X 秒的音频，本项不生效（避免短音频突兀变化）
            row3 = QWidget()
            h3 = QHBoxLayout(row3)
            h3.setContentsMargins(0, 0, 0, 0)
            h3.setSpacing(10)

            lab3a = QLabel("少于")
            lab3a.setObjectName("MutedLabel")

            sp_min = QSpinBox()
            sp_min.setObjectName("VarSpin")
            sp_min.setRange(0, 120)
            sp_min.setSuffix(" 秒")
            sp_min.setFixedHeight(30)
            sp_min.setValue(int(getattr(app_state, minsec_attr, default_minsec) or default_minsec))

            lab3b = QLabel("则不应用本项变化")
            lab3b.setObjectName("MutedLabel")

            h3.addWidget(lab3a)
            h3.addWidget(sp_min)
            h3.addWidget(lab3b)
            h3.addStretch(1)

            v.addWidget(row3)

            def _save_min_sec(vv: int):
                setattr(app_state, minsec_attr, int(vv))
                self.ctx["save_runtime_flag"](minsec_attr, int(vv))

            sp_min.valueChanged.connect(_save_min_sec)


            def _save_enabled(on: bool):
                setattr(app_state, enabled_attr, bool(on))
                self.ctx["save_runtime_flag"](enabled_attr, bool(on))

            def _save_delta():
                d = cmb.currentData()
                setattr(app_state, delta_attr, d)
                self.ctx["save_runtime_flag"](delta_attr, d)

            cb.toggled.connect(_save_enabled)
            cmb.currentIndexChanged.connect(lambda _=None: _save_delta())

            return wrap

        var_body.addWidget(_make_var_block("变调节", "var_pitch_enabled", "var_pitch_delta", "-5~+5", "pitch",
                                       "var_pitch_min_sec", 8))
        var_body.addWidget(_make_var_block("变音量", "var_volume_enabled", "var_volume_delta", "+0~+10", "volume",
                                       "var_volume_min_sec", 3))
        var_body.addWidget(_make_var_block("变语速", "var_speed_enabled", "var_speed_delta", "+0~+10", "speed",
                                       "var_speed_min_sec", 8))

        # 应用对象（主播/助播）
        targets = QWidget()
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
            self.ctx["save_runtime_flag"]("var_apply_anchor", app_state.var_apply_anchor)
            self.ctx["save_runtime_flag"]("var_apply_zhuli", app_state.var_apply_zhuli)

        chk_anchor.toggled.connect(lambda _=None: _save_targets())
        chk_zhuli.toggled.connect(lambda _=None: _save_targets())

        th.addWidget(chk_anchor)
        th.addWidget(chk_zhuli)
        th.addStretch(1)
        var_body.addWidget(targets)

        return var_card

    def _switch_row(self, text: str, sw: QWidget) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(10)
        h.addWidget(QLabel(text))
        h.addStretch(1)
        h.addWidget(sw)
        return w

    def _button_row(self, text: str, btn: QPushButton) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(10)
        h.addWidget(QLabel(text))
        h.addStretch(1)
        h.addWidget(btn)
        return w

    # ---------------- log ----------------
    def _hook_stdout(self):
        if WorkbenchPage._stdout_hooked:
            return
        WorkbenchPage._stdout_hooked = True

        self.log_stream = LogStream()
        self.log_stream.text_written.connect(self.append_log)

        from logger_bootstrap import SafeTee, log_fp
        sys.stdout = SafeTee(self.log_stream, log_fp)
        sys.stderr = SafeTee(self.log_stream, log_fp)

    def append_log(self, text: str):
        self.console.moveCursor(QTextCursor.End)
        self.console.insertPlainText(text)
        self.console.ensureCursorVisible()
        self.console.repaint()

    def clear_log(self):
        self.console.clear()
        print("🧹 日志已清空")

    # ---------------- switches ----------------
    def toggle_danmaku_reply(self, checked: bool):
        app_state.enable_danmaku_reply = bool(checked)
        self.ctx["save_runtime_flag"]("enable_danmaku_reply", app_state.enable_danmaku_reply)
        print("📣 弹幕自动回复已开启" if checked else "📣 弹幕自动回复已关闭")

    def toggle_auto_reply(self, checked: bool):
        app_state.enable_auto_reply = bool(checked)
        self.ctx["save_runtime_flag"]("enable_auto_reply", app_state.enable_auto_reply)
        print("💬 关键词自动回复：已开启" if checked else "💬 关键词自动回复：已关闭")

    def toggle_report_switch(self, checked: bool):
        app_state.enable_voice_report = bool(checked)
        self.ctx["save_runtime_flag"]("enable_voice_report", app_state.enable_voice_report)
        print("⏱ 自动语音报时：已开启" if checked else "⏱ 自动语音报时：已关闭")

    def toggle_zhuli(self, checked: bool):
        app_state.enable_zhuli = bool(checked)
        self.ctx["save_runtime_flag"]("enable_zhuli", app_state.enable_zhuli)
        print("🎧 助播关键词语音：已开启" if checked else "🎧 助播关键词语音：已关闭")

    # ---------------- report interval dialog ----------------
    def set_report_interval(self):
        from audio import voice_reporter

        dlg = QDialog(self)
        dlg.setWindowTitle("⏱ 语音报时间间隔")
        dlg.setFixedSize(320, 180)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(10)

        title = QLabel("设置语音报时间隔（分钟）")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:14px;font-weight:bold;")

        # 🔴 明确提示
        desc = QLabel("⚠ 最低可设置为 5 分钟，低于 5 分钟将自动调整为 5 分钟")
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("color:#C0392B;font-size:12px;")

        spin = QSpinBox()
        spin.setRange(5, 60)  # 最小值强制 5
        spin.setValue(max(5, voice_reporter.REPORT_INTERVAL_MINUTES))
        spin.setSuffix(" 分钟")
        spin.setFixedWidth(160)
        spin.setStyleSheet("color:#000;")

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
        layout.addWidget(desc)  # 提示语
        layout.addLayout(row)
        layout.addStretch(1)
        layout.addLayout(btn_row)

        if dlg.exec() == QDialog.Accepted:
            val = spin.value()
            voice_reporter.REPORT_INTERVAL_MINUTES = val
            voice_reporter.save_report_interval(val)
            self.btn_report_interval.setText(f"⏱ 报时间隔：{val} 分钟")
            print(f"⏱ 报时间隔已设置为：{val} 分钟")

    # ---------------- start system ----------------
    def start_system(self):
        if self._main_started:
            return

        from api.voice_api import VoiceApiClient
        from main import main

        app_state.license_key = self.ctx["license_key"]
        app_state.machine_code = get_machine_code()

        # 如果需要云端音色，先校验默认模型
        if app_state.enable_voice_report or app_state.enable_danmaku_reply:
            try:
                client = VoiceApiClient(BASE_URL, self.ctx["license_key"])
                resp = client.list_models()
                if not isinstance(resp, dict) or resp.get("code") != 0:
                    confirm_dialog(self, "启动失败", f"无法获取云端音色列表：\n{resp}")

                    return

                models = resp.get("data", [])
                if not models:
                    app_state.current_model_id = None
                    confirm_dialog(self, "缺少音色模型",
                                   "当前账号尚未上传任何音色模型，请先到【音色模型】页面上传并设置默认。")
                    self.ctx["jump_to"]("音色模型")
                    return

                default_models = [m for m in models if m.get("is_default")]
                if not default_models:
                    app_state.current_model_id = None
                    confirm_dialog(self, "未设置默认音色", "请先到【音色模型】页面设置一个默认主播音色。")
                    self.ctx["jump_to"]("音色模型")
                    return

                app_state.current_model_id = int(default_models[0]["id"])
            except Exception as e:
                confirm_dialog(self, "启动校验失败", f"音色服务器连接失败：\n{e}")
                return

                return

        self._main_started = True
        self.btn_start.setEnabled(False)

        t = threading.Thread(target=main, args=(self.ctx["license_key"],), daemon=True)
        t.start()
        print("🚀 系统已启动（后台运行）")

    # ---------------- test danmaku ----------------
    def send_test_danmaku(self):
        text = (self.test_input.text() or "").strip()
        if not text:
            return

        print("🧪 本地模拟弹幕：", text)

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
