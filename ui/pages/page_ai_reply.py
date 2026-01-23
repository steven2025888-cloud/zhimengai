# ui/pages/page_ai_reply.py
from __future__ import annotations

from typing import Dict, Any, Optional, List, Tuple

from PySide6.QtCore import Qt, QThread, Signal, QObject, QUrl, QSize
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFrame, QComboBox, QMessageBox, QPlainTextEdit, QButtonGroup, QSizePolicy, QStyle,
    QCheckBox
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
    try:
        import config  # type: ignore
        for n in names:
            if hasattr(config, n):
                val = getattr(config, n)
                if val is None:
                    continue
                if isinstance(val, str) and val.strip() == "":
                    continue
                return val
    except Exception:
        pass
    return default


def _normalize_models(cfg_val: Any) -> List[Tuple[str, str, Optional[str]]]:
    """统一成 [(display_label, model_id, icon_path_or_key), ...]"""
    out: List[Tuple[str, str, Optional[str]]] = []
    if cfg_val is None:
        return out

    if isinstance(cfg_val, dict):
        # dict{label:id} 不带 icon
        for k, v in cfg_val.items():
            label = str(k).strip()
            mid = str(v).strip()
            if label and mid:
                out.append((label, mid, None))
        return out

    if isinstance(cfg_val, (list, tuple)):
        for it in cfg_val:
            if isinstance(it, str):
                s = it.strip()
                if s:
                    out.append((s, s, None))
            elif isinstance(it, dict):
                label = str(it.get("label") or it.get("name") or "").strip()
                mid = str(it.get("id") or it.get("model") or "").strip()
                icon = it.get("icon", None)
                icon = str(icon).strip() if icon else None
                if label and mid:
                    out.append((label, mid, icon))
            elif isinstance(it, (list, tuple)) and len(it) >= 2:
                label = str(it[0]).strip()
                mid = str(it[1]).strip()
                icon = None
                if len(it) >= 3 and it[2]:
                    icon = str(it[2]).strip()
                if label and mid:
                    out.append((label, mid, icon))
    return out


class _TestWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, api_key: str, model: str, user_text: str, host: str, path: str):
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.user_text = user_text
        self.host = host
        self.path = path

    def run(self):
        import http.client
        import json

        conn = None
        try:
            conn = http.client.HTTPSConnection(self.host, timeout=20)
            payload = json.dumps({
                "model": self.model,
                "max_tokens": 128,
                "messages": [
                    {"role": "user", "content": self.user_text or "你好"},
                ],
                "temperature": 1,
                "stream": False,
                "group": "default",
                "top_p": 1,
                "frequency_penalty": 0,
                "presence_penalty": 0
            })
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            conn.request("POST", self.path, payload, headers)
            res = conn.getresponse()
            data = res.read() or b""
            raw = data.decode("utf-8", errors="replace")

            if 200 <= res.status < 300:
                try:
                    obj = json.loads(raw)
                    msg = ""
                    if isinstance(obj, dict):
                        choices = obj.get("choices") or []
                        if isinstance(choices, list) and choices:
                            msg = ((choices[0] or {}).get("message") or {}).get("content") or ""
                    if msg:
                        self.finished.emit(True, f"✅ 测试成功（HTTP {res.status}）\n模型回复：{msg}\n\n原始返回：\n{raw}")
                    else:
                        self.finished.emit(True, f"✅ 测试成功（HTTP {res.status}）\n\n原始返回：\n{raw}")
                except Exception:
                    self.finished.emit(True, f"✅ 测试成功（HTTP {res.status}）\n\n原始返回：\n{raw}")
            else:
                self.finished.emit(False, f"❌ 测试失败（HTTP {res.status}）\n\n返回：\n{raw}")

        except Exception as e:
            self.finished.emit(False, f"❌ 测试异常：{e}")
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass


class AiReplyPage(QWidget):
    def __init__(self, ctx: Optional[dict] = None):
        super().__init__()
        self.ctx = ctx or {}
        self._test_thread: Optional[QThread] = None
        self._test_worker: Optional[_TestWorker] = None
        self._selected_model_id: str = "gpt-5-mini"

        # model_id -> QIcon
        self._model_icons: Dict[str, QIcon] = {}

        self._build_ui()
        self._load_from_runtime()

    # ===================== UI =====================

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("AI回复")
        title.setFont(QFont("微软雅黑", 16, QFont.Bold))
        header.addWidget(title)

        sub = QLabel("（配置 Key / 模型，用于后续 AI 自动回复、改写、弹窗等功能）")
        sub.setObjectName("SubTitle")
        header.addWidget(sub)
        header.addStretch(1)

        self.btn_help = QPushButton("")
        self.btn_help.setObjectName("HelpBtn")
        self.btn_help.setFixedSize(30, 30)
        self.btn_help.setToolTip("打开说明文档")
        # 用标准图标替代“？”（更像产品）
        self.btn_help.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxQuestion))
        self.btn_help.setIconSize(QSize(18, 18))
        self.btn_help.clicked.connect(self.open_help_doc)
        header.addWidget(self.btn_help)

        root.addLayout(header)

        hint = QLabel(
            "使用方法：\n"
            "1）先添加并保存【API Key】\n"
            "2）点击【测试请求】验证 Key / 模型是否可用\n"
            "3）选择默认【AI模型】，后续 AI 回复都会使用\n"
            "提示：模型显示为“名称 + 图标”，请求时会自动使用对应的真实 model_id。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("HintBox")
        root.addWidget(hint)

        # --- Card: API Key
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
        self.btn_open_register.setIcon(self.style().standardIcon(QStyle.SP_DialogHelpButton))
        self.btn_open_register.setIconSize(QSize(16, 16))
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
        self.btn_show.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.btn_show.setIconSize(QSize(16, 16))
        self.btn_show.clicked.connect(self.toggle_show_key)
        row_key.addWidget(self.btn_show)

        self.btn_save_key = QPushButton("保存Key")
        self.btn_save_key.setObjectName("PrimaryBtn")
        self.btn_save_key.setFixedHeight(36)
        self.btn_save_key.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.btn_save_key.setIconSize(QSize(16, 16))
        self.btn_save_key.clicked.connect(self.save_key)
        row_key.addWidget(self.btn_save_key)

        self.btn_test = QPushButton("测试请求")
        self.btn_test.setObjectName("SecondaryBtn")
        self.btn_test.setFixedHeight(36)
        self.btn_test.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_test.setIconSize(QSize(16, 16))
        self.btn_test.clicked.connect(self.test_request)
        row_key.addWidget(self.btn_test)

        lay_key.addLayout(row_key)

        self.txt_test_output = QPlainTextEdit()
        self.txt_test_output.setObjectName("TestOutput")
        self.txt_test_output.setReadOnly(True)
        self.txt_test_output.setPlaceholderText("点击“测试请求”后，这里会显示返回结果…")
        self.txt_test_output.setMinimumHeight(120)
        lay_key.addWidget(self.txt_test_output)

        root.addWidget(card_key)

        # --- Card: Balance
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
        self.btn_refresh.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.btn_refresh.setIconSize(QSize(16, 16))
        self.btn_refresh.clicked.connect(self.refresh_balance)
        row_bal_t.addWidget(self.btn_refresh)
        lay_bal.addLayout(row_bal_t)

        row_bal = QHBoxLayout()
        self.lbl_balance = QLabel("—")
        self.lbl_balance.setStyleSheet("font-size: 18px; font-weight: 800;")
        row_bal.addWidget(self.lbl_balance)
        row_bal.addStretch(1)
        lay_bal.addLayout(row_bal)
        root.addWidget(card_bal)

        # --- Card: Model
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
        self.btn_save_model.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.btn_save_model.setIconSize(QSize(16, 16))
        self.btn_save_model.clicked.connect(self.save_model)
        row_m_t.addWidget(self.btn_save_model)
        lay_m.addLayout(row_m_t)

        self.lbl_model_tip = QLabel("模型名称为展示名（带图标），请求时自动使用真实 model_id。")
        self.lbl_model_tip.setObjectName("SubTitle")
        self.lbl_model_tip.setWordWrap(True)
        lay_m.addWidget(self.lbl_model_tip)

        row_sw = QHBoxLayout()
        self.chk_ai_reply = QCheckBox("启用 AI 改写回复（从关键词回复里随机一句，交给模型改写后发送）")
        self.chk_ai_reply.setObjectName("chk_ai_reply")
        self.chk_ai_reply.stateChanged.connect(self._on_ai_reply_toggle)
        row_sw.addWidget(self.chk_ai_reply, 1)
        lay_m.addLayout(row_sw)


        # 这里用“带图标”的下拉（你要的 logo 风格）
        row_model = QHBoxLayout()
        self.cmb_model = QComboBox()
        self.cmb_model.setObjectName("cmb_ai_model")
        self.cmb_model.setMinimumHeight(36)
        self.cmb_model.currentIndexChanged.connect(self._on_combo_model_changed)
        row_model.addWidget(self.cmb_model, 1)
        lay_m.addLayout(row_model)

        root.addWidget(card_model)
        root.addStretch(1)

        self._apply_local_qss()

    def _on_ai_reply_toggle(self, _):
        _rt_set("ai_reply", bool(self.chk_ai_reply.isChecked()))


    def _apply_local_qss(self):
        self.setStyleSheet(
            """
            QLabel#SubTitle{ color: rgba(230,238,248,0.75); font-size: 12px; }
            QLineEdit#pathEdit, QComboBox#cmb_ai_model{
                background: rgba(0,0,0,0.20);
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 8px;
                padding: 6px 10px;
                color: rgba(230,238,248,0.95);
                font-size: 13px;
            }
            QPlainTextEdit#TestOutput{
                background: rgba(0,0,0,0.22);
                border: 1px solid rgba(255,255,255,0.16);
                border-radius: 10px;
                padding: 8px 10px;
                color: rgba(230,238,248,0.95);
                font-size: 12px;
            }
            QPlainTextEdit#TestOutput:focus{ border: 1px solid rgba(57,113,249,0.55); }
            QLineEdit#pathEdit:hover, QComboBox#cmb_ai_model:hover{
                border: 1px solid rgba(255,255,255,0.28);
                background: rgba(0,0,0,0.26);
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

    # ===================== Model icons =====================

    def _make_icon(self, model_id: str, icon_hint: Optional[str]) -> QIcon:
        """优先：配置的 icon 路径；其次：config.AI_REPLY_MODEL_ICONS 映射；最后：标准图标兜底"""
        # 1) item 自带 icon (路径)
        if icon_hint:
            try:
                ic = QIcon(icon_hint)
                if not ic.isNull():
                    return ic
            except Exception:
                pass

        # 2) 全局映射：AI_REPLY_MODEL_ICONS = {"gpt-5-mini": "xxx.png"}
        icon_map = _cfg_get("AI_REPLY_MODEL_ICONS", "AI_MODEL_ICONS", default=None)
        if isinstance(icon_map, dict):
            p = icon_map.get(model_id) or icon_map.get(model_id.strip())
            if p:
                try:
                    ic = QIcon(str(p))
                    if not ic.isNull():
                        return ic
                except Exception:
                    pass

        # 3) fallback：用 Qt 标准 icon（你如果后续提供 logo 文件，就会自动替换成 logo）
        s = self.style()
        mid = model_id.lower()

        if "5" in mid:
            return s.standardIcon(QStyle.SP_ComputerIcon)
        if "4o" in mid:
            return s.standardIcon(QStyle.SP_DesktopIcon)
        if "4.1" in mid:
            return s.standardIcon(QStyle.SP_DriveHDIcon)
        return s.standardIcon(QStyle.SP_FileIcon)

    def _set_model_options(self, items: List[Tuple[str, str, Optional[str]]]):
        self.cmb_model.blockSignals(True)
        self.cmb_model.clear()
        self._model_icons.clear()

        for label, mid, icon_hint in items:
            ic = self._make_icon(mid, icon_hint)
            self._model_icons[mid] = ic
            # 下拉项带图标 + 展示名，userData 存实际 model_id
            self.cmb_model.addItem(ic, label, mid)

        self.cmb_model.blockSignals(False)

    def _select_model_id(self, model_id: str):
        idx = self.cmb_model.findData(model_id)
        if idx >= 0:
            self.cmb_model.blockSignals(True)
            self.cmb_model.setCurrentIndex(idx)
            self.cmb_model.blockSignals(False)
            self._selected_model_id = model_id
        elif self.cmb_model.count() > 0:
            self._selected_model_id = str(self.cmb_model.currentData() or "gpt-5-mini")

    def _on_combo_model_changed(self, idx: int):
        mid = str(self.cmb_model.currentData() or "").strip()
        if mid:
            self._selected_model_id = mid

    # ===================== Data =====================

    def _load_from_runtime(self):
        st = _rt_get()

        ai_on = bool(st.get("ai_reply", False))
        if hasattr(self, "chk_ai_reply"):
            self.chk_ai_reply.blockSignals(True)
            self.chk_ai_reply.setChecked(ai_on)
            self.chk_ai_reply.blockSignals(False)


        key = str(st.get("ai_api_key", "") or "")
        model_id = str(st.get("ai_model", "") or "")
        balance = st.get("ai_balance", None)

        if key:
            self.edt_key.setText(key)

        cfg_models = _cfg_get("AI_REPLY_MODELS", "AI_MODELS", "OPENAI_MODELS", default=None)
        items = _normalize_models(cfg_models)

        # 默认：展示名 + model_id（你要给用户看的名字），icon 先用 Qt 标准图标兜底
        if not items:
            items = [
                ("极速 · gpt-5-mini（推荐）", "gpt-5-mini", None),
                ("高性价比 · gpt-4o-mini", "gpt-4o-mini", None),
                ("稳定 · gpt-4.1-mini", "gpt-4.1-mini", None),
                ("高质量 · gpt-4.1", "gpt-4.1", None),
                ("旗舰 · gpt-4o", "gpt-4o", None),
            ]

        self._set_model_options(items)
        self._select_model_id(model_id if model_id else items[0][1])

        self.lbl_balance.setText(str(balance) if balance is not None else "—")

    # ===================== Helpers =====================

    def _info(self, title: str, msg: str):
        if confirm_dialog:
            confirm_dialog(self, title, msg)
        else:
            confirm_dialog(self, title, msg)

    def _warn(self, title: str, msg: str):
        if confirm_dialog:
            confirm_dialog(self, title, msg)
        else:
            confirm_dialog(self, title, msg)

    # ===================== Actions =====================

    def toggle_show_key(self):
        if self.edt_key.echoMode() == QLineEdit.Password:
            self.edt_key.setEchoMode(QLineEdit.Normal)
            self.btn_show.setText("隐藏")
        else:
            self.edt_key.setEchoMode(QLineEdit.Password)
            self.btn_show.setText("显示")

    def save_key(self):
        key = (self.edt_key.text() or "").strip()
        if not key:
            self._warn("提示", "请先输入 API Key")
            return
        _rt_set("ai_api_key", key)
        self._info("保存成功", "API Key 已保存（保存在 runtime_state.json）")

    def save_model(self):
        model_id = (self._selected_model_id or "").strip()
        if not model_id:
            self._warn("提示", "请选择一个 AI 模型")
            return
        _rt_set("ai_model", model_id)
        self._info("保存成功", f"默认模型已保存：{model_id}")

    def open_register_url(self):
        url = str(_cfg_get("AI_KEY_REGISTER_URL", "AI_REPLY_REGISTER_URL", "DPS_REGISTER_URL", default="") or "").strip()
        if not url:
            self._warn("未配置网址", "请在 config.py 中配置：AI_KEY_REGISTER_URL")
            return
        QDesktopServices.openUrl(QUrl(url))

    def open_help_doc(self):
        url = str(_cfg_get("AI_REPLY_HELP_URL", "AI_REPLY_DOC_URL", "DPS_HELP_URL", default="") or "").strip()
        if not url:
            self._warn("未配置说明文档", "请在 config.py 中配置：AI_REPLY_HELP_URL")
            return
        QDesktopServices.openUrl(QUrl(url))

    def test_request(self):
        api_key = (self.edt_key.text() or "").strip()
        if not api_key:
            self._warn("提示", "请先输入 API Key，再点击测试。")
            return

        model_id = (self._selected_model_id or "").strip() or "gpt-5-mini"
        host = str(_cfg_get("AI_API_HOST", "API_HOST", default="ai.zhimengai.xyz") or "ai.zhimengai.xyz").strip()
        path = str(_cfg_get("AI_API_PATH", "API_PATH", default="/v1/chat/completions") or "/v1/chat/completions").strip()
        if not path.startswith("/"):
            path = "/" + path

        self.btn_test.setEnabled(False)
        self.btn_test.setText("测试中…")
        self.txt_test_output.setPlainText(f"正在请求 https://{host}{path}\n使用模型：{model_id}\n")

        self._test_thread = QThread(self)
        self._test_worker = _TestWorker(api_key=api_key, model=model_id, user_text="你好", host=host, path=path)
        self._test_worker.moveToThread(self._test_thread)
        self._test_thread.started.connect(self._test_worker.run)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_worker.finished.connect(self._test_thread.quit)
        self._test_worker.finished.connect(self._test_worker.deleteLater)
        self._test_thread.finished.connect(self._test_thread.deleteLater)
        self._test_thread.start()

    def _on_test_finished(self, ok: bool, text: str):
        self.txt_test_output.setPlainText(text)
        self.btn_test.setEnabled(True)
        self.btn_test.setText("测试请求")
        if ok:
            self._info("测试成功", "请求已成功返回。详情见下方输出。")
        else:
            self._warn("测试失败", "请求未通过。详情见下方输出。")

    def refresh_balance(self):
        st = _rt_get()
        bal = st.get("ai_balance", None)
        if bal is None:
            demo = _cfg_get("AI_BALANCE_DEMO", default=None)
            if demo is not None:
                bal = demo
        if bal is None:
            self.lbl_balance.setText("—")
            self._info("提示", "当前未对接余额接口。\n你可以先正常保存 Key/模型，余额后续接入接口再显示。")
            return
        self.lbl_balance.setText(str(bal))
        self._info("刷新完成", f"当前余额：{bal}")
