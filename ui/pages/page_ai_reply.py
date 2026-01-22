# ui/pages/page_ai_reply.py
from __future__ import annotations

import json
from typing import Dict, Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFrame, QComboBox, QMessageBox
)

try:
    from core.runtime_state import load_runtime_state, save_runtime_state
except Exception:
    load_runtime_state = None
    save_runtime_state = None

try:
    from ui.dialogs import confirm_dialog
except Exception:
    confirm_dialog = None


def _rt_get() -> Dict[str, Any]:
    if callable(load_runtime_state):
        try:
            return load_runtime_state() or {}
        except Exception:
            return {}
    return {}


def _rt_set(k: str, v: Any):
    if not callable(save_runtime_state):
        return
    try:
        st = _rt_get()
        st[k] = v
        save_runtime_state(st)
    except Exception:
        pass


def _cfg_get(*names: str, default: Any = "") -> Any:
    """
    兼容不同的 config 命名（你后续想换名字也不影响页面工作）
    """
    try:
        import config  # type: ignore
        for n in names:
            if hasattr(config, n):
                val = getattr(config, n)
                if val is not None and str(val).strip() != "":
                    return val
    except Exception:
        pass
    return default


class AiReplyPage(QWidget):
    """
    AI回复（原 DPS设置）：
    - 添加/保存 API Key
    - 打开“注册/购买 Key”页面
    - 查看算力余额（可选：对接接口后刷新）
    - 选择默认 AI 模型
    """

    def __init__(self, ctx: Optional[dict] = None):
        super().__init__()
        self.ctx = ctx or {}
        self._build_ui()
        self._load_from_runtime()

    # ===================== UI =====================

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # ===== Header =====
        header = QHBoxLayout()
        title = QLabel("AI回复")
        title.setFont(QFont("微软雅黑", 16, QFont.Bold))
        header.addWidget(title)

        sub = QLabel("（配置 Key / 模型，用于后续 AI 自动回复、改写、弹窗等功能）")
        sub.setObjectName("SubTitle")
        header.addWidget(sub)
        header.addStretch(1)

        self.btn_help = QPushButton("？")
        self.btn_help.setObjectName("HelpBtn")
        self.btn_help.setFixedSize(28, 28)
        self.btn_help.setToolTip("打开说明文档")
        self.btn_help.clicked.connect(self.open_help_doc)
        header.addWidget(self.btn_help)

        root.addLayout(header)

        # ===== Hint =====
        hint = QLabel(
            "使用方法：\n"
            "1）先添加并保存【API Key】（用于调用 AI 接口）\n"
            "2）需要 Key 的用户点【注册网址】进行购买/注册\n"
            "3）可选择默认【AI模型】，后续 AI 回复/改写都会用这个模型\n"
            "应用场景：当主播播完“上车挂链接.mp3”，你可让系统自动接一句助播/AI 回复：例如“好的，已上车”。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("HintBox")
        root.addWidget(hint)

        # ===== Card: API Key =====
        card_key = QFrame()
        card_key.setObjectName("Card")
        lay_key = QVBoxLayout(card_key)
        lay_key.setContentsMargins(12, 10, 12, 10)
        lay_key.setSpacing(10)

        row_title = QHBoxLayout()
        lab = QLabel("API Key")
        lab.setObjectName("CardTitle")
        row_title.addWidget(lab)
        row_title.addStretch(1)

        self.btn_open_register = QPushButton("注册网址")
        self.btn_open_register.setObjectName("SecondaryBtn")
        self.btn_open_register.setFixedHeight(34)
        self.btn_open_register.setToolTip("打开注册/购买 API Key 的页面")
        self.btn_open_register.clicked.connect(self.open_register_url)
        row_title.addWidget(self.btn_open_register)

        lay_key.addLayout(row_title)

        row_key = QHBoxLayout()
        self.edt_key = QLineEdit()
        self.edt_key.setObjectName("pathEdit")
        self.edt_key.setPlaceholderText("粘贴你的 API Key（建议保密保存）")
        self.edt_key.setEchoMode(QLineEdit.Password)
        self.edt_key.setMinimumHeight(36)
        row_key.addWidget(self.edt_key, 1)

        self.btn_show = QPushButton("显示")
        self.btn_show.setObjectName("SecondaryBtn")
        self.btn_show.setFixedHeight(36)
        self.btn_show.clicked.connect(self.toggle_show_key)
        row_key.addWidget(self.btn_show)

        self.btn_save_key = QPushButton("保存Key")
        self.btn_save_key.setObjectName("PrimaryBtn")
        self.btn_save_key.setFixedHeight(36)
        self.btn_save_key.clicked.connect(self.save_key)
        row_key.addWidget(self.btn_save_key)

        lay_key.addLayout(row_key)

        root.addWidget(card_key)

        # ===== Card: Balance =====
        card_bal = QFrame()
        card_bal.setObjectName("Card")
        lay_bal = QVBoxLayout(card_bal)
        lay_bal.setContentsMargins(12, 10, 12, 10)
        lay_bal.setSpacing(10)

        row_bal_t = QHBoxLayout()
        lab2 = QLabel("算力余额")
        lab2.setObjectName("CardTitle")
        row_bal_t.addWidget(lab2)
        row_bal_t.addStretch(1)

        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setObjectName("SecondaryBtn")
        self.btn_refresh.setFixedHeight(34)
        self.btn_refresh.clicked.connect(self.refresh_balance)
        row_bal_t.addWidget(self.btn_refresh)

        lay_bal.addLayout(row_bal_t)

        row_bal = QHBoxLayout()
        self.lbl_balance = QLabel("—")
        self.lbl_balance.setStyleSheet("font-size: 18px; font-weight: 800;")
        row_bal.addWidget(self.lbl_balance)
        row_bal.addStretch(1)

        self.lbl_balance_tip = QLabel("（对接接口后可显示实时余额）")
        self.lbl_balance_tip.setObjectName("SubTitle")
        row_bal.addWidget(self.lbl_balance_tip)
        lay_bal.addLayout(row_bal)

        root.addWidget(card_bal)

        # ===== Card: Model =====
        card_model = QFrame()
        card_model.setObjectName("Card")
        lay_m = QVBoxLayout(card_model)
        lay_m.setContentsMargins(12, 10, 12, 10)
        lay_m.setSpacing(10)

        row_m_t = QHBoxLayout()
        lab3 = QLabel("选择AI模型")
        lab3.setObjectName("CardTitle")
        row_m_t.addWidget(lab3)
        row_m_t.addStretch(1)

        self.btn_save_model = QPushButton("保存模型")
        self.btn_save_model.setObjectName("PrimaryBtn")
        self.btn_save_model.setFixedHeight(34)
        self.btn_save_model.clicked.connect(self.save_model)
        row_m_t.addWidget(self.btn_save_model)

        lay_m.addLayout(row_m_t)

        row_m = QHBoxLayout()
        self.cmb_model = QComboBox()
        self.cmb_model.setObjectName("cmb_ai_model")
        self.cmb_model.setMinimumHeight(36)
        row_m.addWidget(self.cmb_model, 1)

        lay_m.addLayout(row_m)
        root.addWidget(card_model)

        root.addStretch(1)

        # 小范围美化：确保深色主题下可读
        self._apply_local_qss()

    def _apply_local_qss(self):
        # 避免你的全局 QSS 没覆盖到这个页面时“字体发白/控件不清楚”
        self.setStyleSheet(
            """
            QLabel#SubTitle{
                color: rgba(230,238,248,0.75);
                font-size: 12px;
            }
            QLineEdit#pathEdit, QComboBox#cmb_ai_model{
                background: rgba(0,0,0,0.20);
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 8px;
                padding: 6px 10px;
                color: rgba(230,238,248,0.95);
                font-size: 13px;
            }
            QLineEdit#pathEdit:hover, QComboBox#cmb_ai_model:hover{
                border: 1px solid rgba(255,255,255,0.28);
                background: rgba(0,0,0,0.26);
            }
            QComboBox#cmb_ai_model::drop-down{
                width: 30px;
                border-left: 1px solid rgba(255,255,255,0.12);
                background: rgba(255,255,255,0.06);
                border-top-right-radius: 8px;
                border-bottom-right-radius: 8px;
            }
            QComboBox QAbstractItemView{
                background: rgba(18,22,30,0.98);
                color: rgba(230,238,248,0.95);
                border: 1px solid rgba(255,255,255,0.16);
                selection-background-color: rgba(57,113,249,0.65);
                outline: 0;
                padding: 6px;
            }
            """
        )

    # ===================== Data =====================

    def _load_from_runtime(self):
        st = _rt_get()
        key = str(st.get("ai_api_key", "") or "")
        model = str(st.get("ai_model", "") or "")
        balance = st.get("ai_balance", None)

        if key:
            self.edt_key.setText(key)

        # 模型列表：优先用 config.AI_REPLY_MODELS / AI_MODELS / OPENAI_MODELS
        models = _cfg_get("AI_REPLY_MODELS", "AI_MODELS", "OPENAI_MODELS", default=None)
        if isinstance(models, (list, tuple)) and models:
            items = [str(x) for x in models if str(x).strip()]
        else:
            items = [
                "gpt-4o-mini",
                "gpt-4.1-mini",
                "gpt-4.1",
                "gpt-4o",
            ]
        self.cmb_model.clear()
        self.cmb_model.addItems(items)

        if model and model in items:
            self.cmb_model.setCurrentText(model)
        else:
            # config 默认模型
            default_model = str(_cfg_get("AI_REPLY_DEFAULT_MODEL", "AI_DEFAULT_MODEL", default="") or "")
            if default_model in items:
                self.cmb_model.setCurrentText(default_model)

        if balance is not None:
            self.lbl_balance.setText(str(balance))
        else:
            self.lbl_balance.setText("—")

    # ===================== Actions =====================

    def toggle_show_key(self):
        if self.edt_key.echoMode() == QLineEdit.Password:
            self.edt_key.setEchoMode(QLineEdit.Normal)
            self.btn_show.setText("隐藏")
        else:
            self.edt_key.setEchoMode(QLineEdit.Password)
            self.btn_show.setText("显示")

    def _info(self, title: str, msg: str):
        if confirm_dialog:
            confirm_dialog(self, title, msg)
        else:
            QMessageBox.information(self, title, msg)

    def _warn(self, title: str, msg: str):
        if confirm_dialog:
            confirm_dialog(self, title, msg)
        else:
            QMessageBox.warning(self, title, msg)

    def save_key(self):
        key = (self.edt_key.text() or "").strip()
        if not key:
            self._warn("提示", "请先输入 API Key")
            return
        _rt_set("ai_api_key", key)
        self._info("保存成功", "API Key 已保存（保存在 runtime_state.json）")

    def save_model(self):
        model = (self.cmb_model.currentText() or "").strip()
        if not model:
            self._warn("提示", "请选择一个 AI 模型")
            return
        _rt_set("ai_model", model)
        self._info("保存成功", f"默认模型已保存：{model}")

    def open_register_url(self):
        url = str(_cfg_get(
            "AI_KEY_REGISTER_URL",
            "AI_REPLY_REGISTER_URL",
            "DPS_REGISTER_URL",
            "REGISTER_API_KEY_URL",
            default=""
        ) or "").strip()

        if not url:
            self._warn("未配置网址", "请在 config.py 中配置：AI_KEY_REGISTER_URL（或 AI_REPLY_REGISTER_URL）")
            return

        try:
            QDesktopServices.openUrl(url)
        except Exception:
            # Qt 可能需要 QUrl
            try:
                from PySide6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl(url))
            except Exception as e:
                self._warn("打开失败", str(e))

    def open_help_doc(self):
        url = str(_cfg_get(
            "AI_REPLY_HELP_URL",
            "AI_REPLY_DOC_URL",
            "DPS_HELP_URL",
            "DPS_DOC_URL",
            default=""
        ) or "").strip()

        if not url:
            self._warn("未配置说明文档", "请在 config.py 中配置：AI_REPLY_HELP_URL（或 AI_REPLY_DOC_URL）")
            return

        try:
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(url))
        except Exception as e:
            self._warn("打开失败", str(e))

    def refresh_balance(self):
        """
        这里先做“UI可用”的版本：显示 runtime_state 里缓存的余额。
        你后面接接口时，只要在这里用 key 调你后端/第三方接口，然后 _rt_set('ai_balance', xxx) 即可。
        """
        st = _rt_get()
        bal = st.get("ai_balance", None)
        if bal is None:
            # 尝试从 config 写死一个演示余额（可选）
            demo = _cfg_get("AI_BALANCE_DEMO", default=None)
            if demo is not None:
                bal = demo

        if bal is None:
            self.lbl_balance.setText("—")
            self._info("提示", "当前未对接余额接口。\n你可以先正常保存 Key/模型，余额后续接入接口再显示。")
            return

        self.lbl_balance.setText(str(bal))
        self._info("刷新完成", f"当前余额：{bal}")
