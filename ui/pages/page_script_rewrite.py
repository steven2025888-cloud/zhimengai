# ui/pages/page_script_rewrite.py
from __future__ import annotations

import os
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from PySide6.QtCore import Qt, QThread, Signal, QObject, QUrl, QSize, QRect, QPoint
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFrame, QComboBox, QMessageBox, QPlainTextEdit, QButtonGroup,
    QListWidget, QListWidgetItem, QStyle, QCheckBox,
    QToolButton, QLayout, QLayoutItem, QScrollArea
)
from ui.dialogs import confirm_dialog


try:
    from core.runtime_state import load_runtime_state, save_runtime_state
except Exception:
    load_runtime_state = None
    save_runtime_state = None



# ===================== runtime helpers =====================

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


def _safe_filename(name: str) -> str:
    name = (name or "").strip().replace("\n", " ").replace("\r", " ")
    bad = '<>:"/\\|?*'
    for c in bad:
        name = name.replace(c, "_")
    name = " ".join(name.split())
    return name[:80] if len(name) > 80 else name


def _app_dir() -> Path:
    base = _cfg_get("BASE_DIR", default=None)
    if base:
        try:
            return Path(str(base))
        except Exception:
            pass
    gad = _cfg_get("get_app_dir", default=None)
    if callable(gad):
        try:
            return Path(str(gad()))
        except Exception:
            pass
    return Path(os.getcwd()).resolve()


def _rewrite_dir() -> Path:
    p = _app_dir() / "话术改写"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _split_keywords_text(s: str) -> List[str]:
    """
    过滤关键词：主推“回车/换行/空白”拆分，同时兼容老数据里的逗号/顿号。
    """
    s = (s or "").strip()
    if not s:
        return []
    for sep in [",", "，", "、", ";", "；"]:
        s = s.replace(sep, "\n")
    parts: List[str] = []
    for line in s.splitlines():
        line = (line or "").strip()
        if not line:
            continue
        for p in line.split():
            p = p.strip()
            if p:
                parts.append(p)
    out: List[str] = []
    seen = set()
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _trim_overlap(prev: str, new: str, max_check: int = 300) -> str:
    """
    续写时常出现“重复一小段”，做一个很轻量的 overlap 去重。
    """
    if not prev or not new:
        return new
    a = prev[-max_check:]
    b = new[:max_check]
    best = 0
    # 找最长公共后缀/前缀
    for k in range(1, min(len(a), len(b)) + 1):
        if a[-k:] == b[:k]:
            best = k
    return new[best:]


# ===================== UI helpers =====================

class FlowLayout(QLayout):
    """轻量 FlowLayout（Qt 示例改造）"""

    def __init__(self, parent=None, margin=0, hspacing=8, vspacing=8):
        super().__init__(parent)
        self._items: List[QLayoutItem] = []
        self._hspacing = hspacing
        self._vspacing = vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item: QLayoutItem):
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        size += QSize(left + right, top + bottom)
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        x = rect.x()
        y = rect.y()
        line_height = 0

        left, top, right, bottom = self.getContentsMargins()
        effective_rect = rect.adjusted(left, top, -right, -bottom)
        x = effective_rect.x()
        y = effective_rect.y()
        max_w = effective_rect.width()

        for item in self._items:
            wid = item.widget()
            if not wid or not wid.isVisible():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + self._hspacing
            if next_x - self._hspacing > effective_rect.x() + max_w and line_height > 0:
                x = effective_rect.x()
                y = y + line_height + self._vspacing
                next_x = x + hint.width() + self._hspacing
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))

            x = next_x
            line_height = max(line_height, hint.height())

        return (y + line_height + bottom) - rect.y()


class KeywordChips(QWidget):
    """过滤关键词：回车/失焦 自动变 chip"""
    changed = Signal()

    def __init__(self, placeholder: str = "输入过滤词，回车添加；或粘贴多行", parent=None):
        super().__init__(parent)
        self._words: List[str] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        self.edt = QLineEdit()
        self.edt.setObjectName("kwInput")
        self.edt.setPlaceholderText(placeholder)
        self.edt.setMinimumHeight(34)

        self.btn_add = QPushButton("添加")
        self.btn_add.setObjectName("SecondaryBtn")
        self.btn_add.setFixedHeight(34)

        top.addWidget(self.edt, 1)
        top.addWidget(self.btn_add, 0)
        lay.addLayout(top)

        chips_box = QFrame()
        chips_box.setObjectName("ChipsBox")
        chips_box_l = QVBoxLayout(chips_box)
        chips_box_l.setContentsMargins(10, 10, 10, 10)
        chips_box_l.setSpacing(0)

        self.flow_host = QWidget()
        self.flow = FlowLayout(self.flow_host, margin=0, hspacing=8, vspacing=8)
        self.flow_host.setLayout(self.flow)
        chips_box_l.addWidget(self.flow_host)

        lay.addWidget(chips_box)

        self.btn_add.clicked.connect(self._commit_current)
        self.edt.returnPressed.connect(self._commit_current)
        self.edt.editingFinished.connect(self._commit_current)

    def words(self) -> List[str]:
        return list(self._words)

    def set_words(self, words: List[str]):
        words = [str(x).strip() for x in (words or []) if str(x).strip()]
        out = []
        seen = set()
        for w in words:
            if w in seen:
                continue
            seen.add(w)
            out.append(w)
        self._words = out

        while self.flow.count():
            it = self.flow.takeAt(0)
            if it and it.widget():
                it.widget().deleteLater()

        for w in self._words:
            self._add_chip_widget(w)

        self.changed.emit()

    def add_words_from_text(self, text: str):
        words = _split_keywords_text(text)
        if not words:
            return
        cur = self.words()
        for w in words:
            if w not in cur:
                cur.append(w)
        self.set_words(cur)

    def _commit_current(self):
        txt = (self.edt.text() or "").strip()
        if not txt:
            return
        self.add_words_from_text(txt)
        self.edt.clear()

    def _add_chip_widget(self, word: str):
        btn = QPushButton(f"{word}  ✕")
        btn.setObjectName("Chip")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self._remove_word(word))
        self.flow.addWidget(btn)

    def _remove_word(self, word: str):
        cur = [w for w in self._words if w != word]
        self.set_words(cur)


class CollapsibleSection(QWidget):
    """可折叠区域"""
    def __init__(self, title: str, content: QWidget, parent=None, checked: bool = True):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        bar = QToolButton()
        bar.setText(title)
        bar.setCheckable(True)
        bar.setChecked(checked)
        bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        bar.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        bar.setObjectName("FoldBar")
        bar.setCursor(Qt.PointingHandCursor)

        def _toggle():
            on = bar.isChecked()
            bar.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
            content.setVisible(on)

        bar.toggled.connect(lambda _: _toggle())

        root.addWidget(bar)
        root.addWidget(content)
        content.setVisible(checked)


# ===================== worker =====================

class _RewriteWorker(QObject):
    finished = Signal(bool, dict)  # ok, payload(dict)

    def __init__(self, api_key: str, model: str, mode: str, text: str,
                 extra_on: bool, extra: str,
                 filt_on: bool, filt_words: List[str],
                 host: str, path: str):
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.mode = mode
        self.text = text
        self.extra_on = extra_on
        self.extra = extra
        self.filt_on = filt_on
        self.filt_words = filt_words or []
        self.host = host
        self.path = path

    def _build_prompt(self) -> str:
        base_rules = [
            "你是一名顶级电商直播话术策划与文案改写专家。",
            "目标：在不改变核心意思的前提下，让话术更自然、更口语、更有转化、更适合直播口播。",
            "输出要求：只输出改写后的话术正文，不要输出解释、不要输出分析过程。",
            "保留关键信息：价格、赠品、活动规则、时间限制等必须保留且清晰。",
            "字数要求：改写后的总字数不得少于原文总字数；内容不足时必须补充完善，而不是省略。",
        ]

        if self.mode == "quick":
            mode_rules = [
                "模式：快速改写。",
                "要求：尽量少改结构，主要优化用词与节奏，去重、提顺滑、增强感染力。",
                "长度：与原文相当或更长。",
            ]
        else:
            mode_rules = [
                "模式：深度改写。",
                "要求：可以重组结构，增强逻辑层次与带货节奏（引入-利益点-证据-行动号召）。",
                "输出：给出 2 个版本，用“版本A：”“版本B：”分隔。",
                "长度：两个版本加起来总字数不得少于原文。",
            ]

        extra_rules = []
        if self.extra_on and (self.extra or "").strip():
            extra_rules.append("附加要求（必须遵守）：")
            extra_rules.append((self.extra or "").strip())

        filt_rules = []
        if self.filt_on and self.filt_words:
            filt_rules.append("过滤关键词（禁止出现以下词/短语；能替换就替换；不能替换就通过改写规避）：")
            filt_rules.append("\n".join(self.filt_words))

        prompt = "\n".join(base_rules + mode_rules + extra_rules + filt_rules)
        prompt += "\n\n---\n原文如下（注意：这是需要改写的输入，不是最终要直接发布的话术）：\n" + (self.text or "").strip()
        return prompt

    @staticmethod
    def _extract_meta(obj: dict) -> Tuple[str, dict]:
        finish_reason = ""
        usage = {}
        try:
            choices = obj.get("choices") or []
            if isinstance(choices, list) and choices:
                finish_reason = str((choices[0] or {}).get("finish_reason") or "")
        except Exception:
            pass
        try:
            usage = obj.get("usage", {}) or {}
        except Exception:
            usage = {}
        return finish_reason, usage

    @staticmethod
    def _extract_text(obj: dict) -> str:
        msg = ""
        if isinstance(obj, dict):
            choices = obj.get("choices") or []
            if isinstance(choices, list) and choices:
                msg = (((choices[0] or {}).get("message") or {}).get("content") or "") or ""
        return (msg or "").strip()

    def _make_system_agent(self) -> str:
        return (
            "作为【话术改写智能体】，我会根据您提供的【待改写原文】，在保持原意的基础上进行创造性改写与深度润色。字数只能多不能少，字数只能多不能少，字数只能多不能少，我会将原文内容转化为更生动自然、更具感染力和说服力的口语化表达，同时优化其结构以增强转化效果。在输出时，我不会直接复制原文，而是通过扩充细节、丰富描述、调整句式、强化亮点等方式，确保改写后的内容比原文更详尽、更饱满，字数只增不减。除最终改写结果外，我不作任何额外解释或说明\n"
        )

    def _request_once(self, conn, messages: list, max_tokens: int) -> Tuple[int, str, dict]:
        """
        return: (http_status, raw_text, obj_or_empty)
        """
        group_val = str(_cfg_get("AI_API_GROUP", "AI_GROUP", "REWRITE_GROUP", default="") or "").strip()

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7 if self.mode == "quick" else 0.85,
            "top_p": 1,
            "stream": False,
            "group": "vip",  # 兼容你服务器如果只认 /pg/chat/completions；无害字段
        }
        # 若 config 未配置 group，就不覆盖
        if group_val:
            payload["group"] = group_val

        body = json.dumps(payload, ensure_ascii=False)

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        conn.request("POST", self.path, body.encode("utf-8"), headers)
        res = conn.getresponse()
        raw_bytes = res.read() or b""
        raw = raw_bytes.decode("utf-8", errors="replace")
        try:
            obj = json.loads(raw)
        except Exception:
            obj = {}
        return res.status, raw, obj

    def run(self):
        import http.client

        started = time.time()
        in_text = (self.text or "").strip()
        input_chars = len(in_text)

        payload_out: Dict[str, Any] = {
            "ok": False,
            "mode": self.mode,
            "model": self.model,
            "elapsed_ms": 0,
            "error": "",
            "result_text": "",
            "raw_list": [],
            "finish_reason": "",
            "usage": {},
            "input_chars": input_chars,
            "output_chars": 0,
            "tries": 1,
            "debug": [],
        }

        conn = None
        try:
            conn = http.client.HTTPSConnection(self.host, timeout=120)

            prompt = self._build_prompt()
            system_agent = self._make_system_agent()

            messages = [
                {"role": "system", "content": system_agent},
                {"role": "user", "content": prompt},
            ]
            # —— 不做“字数不足”限制：只要有返回就展示/落盘 ——
            # —— 单次 max_tokens（不做分段/不做多次续写）——
            # 你可以在 config 里配：REWRITE_MAX_TOKENS_QUICK / REWRITE_MAX_TOKENS_DEEP
            cfg_q = int(_cfg_get("REWRITE_MAX_TOKENS_QUICK", default=12000) or 12000)
            cfg_d = int(_cfg_get("REWRITE_MAX_TOKENS_DEEP", default=16000) or 16000)
            max_tokens_each = cfg_q if self.mode == "quick" else cfg_d

            status, raw, obj = self._request_once(conn, messages, max_tokens=max_tokens_each)
            payload_out["raw_list"].append((raw or "")[:3000])

            if not (200 <= status < 300):
                payload_out["error"] = f"HTTP {status}"
                payload_out["debug"].append(f"http={status}")
                self.finished.emit(False, payload_out)
                return

            finish_reason, usage = self._extract_meta(obj)
            out_text = self._extract_text(obj)

            payload_out["finish_reason"] = finish_reason
            payload_out["usage"] = usage
            payload_out["debug"].append(f"finish_reason={finish_reason} usage={usage} got_chars={len(out_text)}")

            if not out_text:
                payload_out["error"] = "返回内容为空"
                self.finished.emit(False, payload_out)
                return

            out_chars = len(out_text.strip())
            payload_out["output_chars"] = out_chars
            # ✅ 只发一次：不做“字数不足”拦截，直接视为成功
            payload_out["ok"] = True
            payload_out["result_text"] = out_text.strip()
            self.finished.emit(True, payload_out)

        except Exception as e:
            payload_out["error"] = str(e)
            self.finished.emit(False, payload_out)
        finally:
            payload_out["elapsed_ms"] = int((time.time() - started) * 1000)
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
# ===================== status item widget =====================

class StatusItemWidget(QWidget):
    """成功任务左侧有“打开文本”按钮"""

    def __init__(self, rec: dict, open_cb, parent=None):
        super().__init__(parent)
        self.rec = rec or {}
        self.open_cb = open_cb

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(10)

        btn = QPushButton()
        btn.setObjectName("OpenMiniBtn")
        btn.setFixedSize(30, 30)
        btn.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        btn.setIconSize(QSize(16, 16))
        btn.setToolTip("打开文本")
        btn.clicked.connect(lambda: self.open_cb(self.rec))
        root.addWidget(btn, 0)

        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(2)

        ts = str(self.rec.get("time", "") or "")
        mode = str(self.rec.get("mode", "") or "")
        model = str(self.rec.get("model", "") or "")
        path = str(self.rec.get("path", "") or "")
        name = os.path.basename(path) if path else ""

        title = QLabel(f"{name}")
        title.setObjectName("StatusTitle")

        sub = QLabel(f"{ts}  ·  {mode}  ·  {model}")
        sub.setObjectName("StatusSub")

        info.addWidget(title)
        info.addWidget(sub)
        root.addLayout(info, 1)


# ===================== page =====================

class ScriptRewritePage(QWidget):
    """
    话术改写：
    - 固定高度：内部滚动（QScrollArea），不会被展开撑满屏
    - 深色背景：scroll viewport 透明，避免白底
    - 可选项默认关闭（折叠收起）
    - 失败不记录；成功记录支持一键打开
    - finish_reason/usage/字数/重试次数记录到日志
    - 单次提交：不做分段/不做续写（只请求一次）
    - 输出 txt 不保存原文
    - 完成后询问是否立即打开（Yes/No）
    """

    def __init__(self, ctx: Optional[dict] = None):
        super().__init__()
        self.ctx = ctx or {}
        self._thread: Optional[QThread] = None
        self._worker: Optional[_RewriteWorker] = None

        self._selected_model_id: str = ""
        self._model_icons: Dict[str, QIcon] = {}

        self._build_ui()
        self._apply_local_qss()
        self._load_from_runtime()
        self._reload_history_list()

    # ---------------- UI ----------------

    def _build_ui(self):
        # 外层固定：只放一个 ScrollArea
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)

        self.setObjectName("RewritePage")

        self.scroll = QScrollArea()
        self.scroll.setObjectName("RewriteScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        outer.addWidget(self.scroll)

        self.content = QWidget()
        self.content.setObjectName("RewriteContent")
        self.scroll.setWidget(self.content)

        root = QVBoxLayout(self.content)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("话术改写")
        title.setFont(QFont("微软雅黑", 16, QFont.Bold))
        header.addWidget(title)

        sub = QLabel("（生成可直接口播的改写稿；结果保存为 txt；可选项和历史会保存，但原文不保存）")
        sub.setObjectName("SubTitle")
        header.addWidget(sub)
        header.addStretch(1)

        self.btn_open_dir = QPushButton("打开目录")
        self.btn_open_dir.setObjectName("SecondaryBtn")
        self.btn_open_dir.setFixedHeight(32)
        self.btn_open_dir.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.btn_open_dir.setIconSize(QSize(16, 16))
        self.btn_open_dir.clicked.connect(self.open_rewrite_dir)
        header.addWidget(self.btn_open_dir)
        root.addLayout(header)

        # 使用说明（默认收起）
        usage_box = QFrame()
        usage_box.setObjectName("Card")
        usage_l = QVBoxLayout(usage_box)
        usage_l.setContentsMargins(12, 10, 12, 10)
        usage_l.setSpacing(8)

        hint = QLabel(
            "使用方法：\n"
            "1）保存 API Key；选择模型\n"
            "2）输入原文\n"
            "3）可选：勾选“附加要求/过滤关键词”才会提交\n"
            "4）选择模式提交\n"
            "5）成功后保存 txt，并显示在任务状态（左侧按钮一键打开）\n"
            "6）若输出不足，会自动续写补齐（最多几轮）"
        )
        hint.setWordWrap(True)
        hint.setObjectName("HintBox")
        usage_l.addWidget(hint)
        root.addWidget(CollapsibleSection("使用说明（点击收起/展开）", usage_box, checked=False))

        # 顶部：key + model
        row_top = QHBoxLayout()
        row_top.setSpacing(12)

        card_key = QFrame()
        card_key.setObjectName("Card")
        key_l = QVBoxLayout(card_key)
        key_l.setContentsMargins(12, 10, 12, 10)
        key_l.setSpacing(8)

        t = QHBoxLayout()
        lab = QLabel("API Key")
        lab.setObjectName("CardTitle")
        t.addWidget(lab)
        t.addStretch(1)

        self.btn_save_key = QPushButton("保存Key")
        self.btn_save_key.setObjectName("PrimaryBtn")
        self.btn_save_key.setFixedHeight(32)
        self.btn_save_key.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.btn_save_key.setIconSize(QSize(16, 16))
        self.btn_save_key.clicked.connect(self.save_key)
        t.addWidget(self.btn_save_key)
        key_l.addLayout(t)

        krow = QHBoxLayout()
        self.edt_key = QLineEdit()
        self.edt_key.setObjectName("pathEdit")
        self.edt_key.setEchoMode(QLineEdit.Password)
        self.edt_key.setPlaceholderText("粘贴 API Key（保存在 runtime_state.json）")
        self.edt_key.setMinimumHeight(34)
        krow.addWidget(self.edt_key, 1)

        self.btn_show = QPushButton("显示")
        self.btn_show.setObjectName("SecondaryBtn")
        self.btn_show.setFixedHeight(34)
        self.btn_show.clicked.connect(self.toggle_show_key)
        krow.addWidget(self.btn_show)
        key_l.addLayout(krow)

        card_model = QFrame()
        card_model.setObjectName("Card")
        model_l = QVBoxLayout(card_model)
        model_l.setContentsMargins(12, 10, 12, 10)
        model_l.setSpacing(8)

        t2 = QHBoxLayout()
        lab2 = QLabel("选择模型")
        lab2.setObjectName("CardTitle")
        t2.addWidget(lab2)
        t2.addStretch(1)

        self.btn_save_model = QPushButton("保存模型")
        self.btn_save_model.setObjectName("PrimaryBtn")
        self.btn_save_model.setFixedHeight(32)
        self.btn_save_model.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.btn_save_model.setIconSize(QSize(16, 16))
        self.btn_save_model.clicked.connect(self.save_model)
        t2.addWidget(self.btn_save_model)
        model_l.addLayout(t2)

        self.cmb_model = QComboBox()
        self.cmb_model.setObjectName("cmb_ai_model")
        self.cmb_model.setMinimumHeight(34)
        self.cmb_model.currentIndexChanged.connect(self._on_combo_model_changed)
        model_l.addWidget(self.cmb_model)

        row_top.addWidget(card_key, 1)
        row_top.addWidget(card_model, 1)
        root.addLayout(row_top)

        # 原文输入
        card_in = QFrame()
        card_in.setObjectName("Card")
        in_l = QVBoxLayout(card_in)
        in_l.setContentsMargins(12, 10, 12, 10)
        in_l.setSpacing(10)

        rtt = QHBoxLayout()
        lab3 = QLabel("原文（必填）")
        lab3.setObjectName("CardTitle")
        rtt.addWidget(lab3)
        rtt.addStretch(1)
        self.lbl_count = QLabel("0 字")
        self.lbl_count.setObjectName("SubTitle")
        rtt.addWidget(self.lbl_count)
        in_l.addLayout(rtt)

        self.txt_input = QPlainTextEdit()
        self.txt_input.setObjectName("TextArea")
        self.txt_input.setPlaceholderText("把你要改写的口播稿/话术粘贴到这里…")
        self.txt_input.setMinimumHeight(150)
        self.txt_input.textChanged.connect(self._on_input_changed)
        in_l.addWidget(self.txt_input)
        root.addWidget(card_in)

        # 可选项（默认关闭：折叠收起）
        card_opt = QFrame()
        card_opt.setObjectName("Card")
        opt_l = QVBoxLayout(card_opt)
        opt_l.setContentsMargins(12, 10, 12, 10)
        opt_l.setSpacing(10)

        lab4 = QLabel("可选项（勾选才提交）")
        lab4.setObjectName("CardTitle")
        opt_l.addWidget(lab4)

        extra_row = QHBoxLayout()
        self.chk_extra = QCheckBox("附加要求（选择才提交）")
        self.chk_extra.setObjectName("OptCheck")
        self.chk_extra.stateChanged.connect(self._persist_inputs)
        extra_row.addWidget(self.chk_extra)
        extra_row.addStretch(1)
        opt_l.addLayout(extra_row)

        self.txt_extra = QPlainTextEdit()
        self.txt_extra.setObjectName("TextAreaSmall")
        self.txt_extra.setPlaceholderText("例如：语气更强势/更温柔；必须包含“现在下单”；更短更直接…")
        self.txt_extra.setMinimumHeight(86)
        self.txt_extra.textChanged.connect(self._persist_inputs)
        opt_l.addWidget(self.txt_extra)

        filter_row = QHBoxLayout()
        self.chk_filter = QCheckBox("过滤关键词（选择才提交）")
        self.chk_filter.setObjectName("OptCheck")
        self.chk_filter.stateChanged.connect(self._persist_inputs)
        filter_row.addWidget(self.chk_filter)
        filter_row.addStretch(1)
        opt_l.addLayout(filter_row)

        self.filter_chips = KeywordChips(placeholder="输入过滤词，回车添加；或粘贴多行（不需要逗号）")
        self.filter_chips.changed.connect(self._persist_inputs)
        opt_l.addWidget(self.filter_chips)

        root.addWidget(CollapsibleSection("可选项（点击收起/展开）", card_opt, checked=False))

        # 模式 + 提交
        row_action = QHBoxLayout()
        row_action.setSpacing(10)

        mode_box = QFrame()
        mode_box.setObjectName("PillBox")
        ml = QHBoxLayout(mode_box)
        ml.setContentsMargins(10, 6, 10, 6)
        ml.setSpacing(8)

        self.btn_quick = QPushButton("快速改写")
        self.btn_deep = QPushButton("深度改写")
        for b in (self.btn_quick, self.btn_deep):
            b.setCheckable(True)
            b.setObjectName("PillBtn")
            b.setMinimumHeight(30)

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.btn_quick, 1)
        self.mode_group.addButton(self.btn_deep, 2)
        self.btn_quick.setChecked(True)
        self.mode_group.buttonClicked.connect(self._persist_inputs)

        ml.addWidget(self.btn_quick)
        ml.addWidget(self.btn_deep)

        row_action.addWidget(mode_box, 0)
        row_action.addStretch(1)

        self.btn_submit = QPushButton("提交改写")
        self.btn_submit.setObjectName("PrimaryBtn")
        self.btn_submit.setFixedHeight(36)
        self.btn_submit.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_submit.setIconSize(QSize(18, 18))
        self.btn_submit.clicked.connect(self.submit)
        row_action.addWidget(self.btn_submit, 0)
        root.addLayout(row_action)

        # 状态
        card_status = QFrame()
        card_status.setObjectName("Card")
        st_l = QVBoxLayout(card_status)
        st_l.setContentsMargins(12, 10, 12, 10)
        st_l.setSpacing(8)

        stt = QHBoxLayout()
        lab5 = QLabel("任务状态（仅成功记录）")
        lab5.setObjectName("CardTitle")
        stt.addWidget(lab5)
        stt.addStretch(1)

        self.btn_refresh_list = QPushButton("刷新")
        self.btn_refresh_list.setObjectName("SecondaryBtn")
        self.btn_refresh_list.setFixedHeight(30)
        self.btn_refresh_list.clicked.connect(self._reload_history_list)
        stt.addWidget(self.btn_refresh_list)

        self.btn_clear = QPushButton("清空记录")
        self.btn_clear.setObjectName("DangerBtn")
        self.btn_clear.setFixedHeight(30)
        self.btn_clear.clicked.connect(self.clear_history)
        stt.addWidget(self.btn_clear)

        st_l.addLayout(stt)

        self.list_status = QListWidget()
        self.list_status.setObjectName("StatusList")
        self.list_status.setMinimumHeight(150)
        self.list_status.itemDoubleClicked.connect(self._open_selected_item)  # 只连一次
        st_l.addWidget(self.list_status)

        self.txt_log = QPlainTextEdit()
        self.txt_log.setObjectName("TestOutput")
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(110)
        self.txt_log.setPlaceholderText("这里显示最近一次任务的日志（finish_reason/usage/字数/续写次数/保存路径等）…")
        st_l.addWidget(self.txt_log)

        root.addWidget(card_status)
        root.addStretch(1)

    def _apply_local_qss(self):
        # ✅ 修复白底：scrollarea/viewport 全透明，让主窗口深色背景透出来
        self.setStyleSheet(
            """
            QWidget#RewritePage{ background: transparent; }
            QScrollArea#RewriteScroll{ background: transparent; border: 0px; }
            QScrollArea#RewriteScroll QWidget{ background: transparent; }
            QWidget#RewriteContent{ background: transparent; }
            QScrollArea#RewriteScroll QWidget#qt_scrollarea_viewport{ background: transparent; }

            QLabel#SubTitle{ color: rgba(230,238,248,0.72); font-size: 12px; }
            QLabel#CardTitle{ color: rgba(230,238,248,0.95); font-size: 13px; font-weight: 800; }

            QToolButton#FoldBar{
                background: rgba(0,0,0,0.12);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
                padding: 8px 10px;
                color: rgba(230,238,248,0.92);
                font-weight: 900;
            }
            QToolButton#FoldBar:hover{ background: rgba(255,255,255,0.06); }

            QFrame#Card{
                background: rgba(0,0,0,0.18);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 14px;
            }
            QLabel#HintBox{
                background: rgba(0,0,0,0.14);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
                padding: 10px 12px;
                color: rgba(230,238,248,0.88);
                font-size: 12px;
            }

            QLineEdit#pathEdit, QComboBox#cmb_ai_model, QLineEdit#kwInput{
                background: rgba(0,0,0,0.20);
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 10px;
                padding: 7px 10px;
                color: rgba(230,238,248,0.95);
                font-size: 13px;
            }
            QLineEdit#pathEdit:hover, QComboBox#cmb_ai_model:hover, QLineEdit#kwInput:hover{
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

            QPlainTextEdit#TextArea{
                background: rgba(0,0,0,0.22);
                border: 1px solid rgba(255,255,255,0.14);
                border-radius: 12px;
                padding: 10px 10px;
                color: rgba(230,238,248,0.95);
                font-size: 13px;
            }
            QPlainTextEdit#TextAreaSmall{
                background: rgba(0,0,0,0.18);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 12px;
                padding: 8px 10px;
                color: rgba(230,238,248,0.92);
                font-size: 12px;
            }

            QPlainTextEdit#TestOutput{
                background: rgba(0,0,0,0.22);
                border: 1px solid rgba(255,255,255,0.16);
                border-radius: 12px;
                padding: 8px 10px;
                color: rgba(230,238,248,0.95);
                font-size: 12px;
            }

            QCheckBox#OptCheck{
                color: rgba(230,238,248,0.92);
                font-size: 12px;
                font-weight: 700;
            }

            QFrame#PillBox{
                background: rgba(0,0,0,0.16);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 999px;
            }
            QPushButton#PillBtn{
                background: transparent;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 999px;
                padding: 4px 12px;
                color: rgba(230,238,248,0.90);
                font-weight: 800;
            }
            QPushButton#PillBtn:checked{
                background: rgba(57,113,249,0.55);
                border: 1px solid rgba(57,113,249,0.70);
            }

            QListWidget#StatusList{
                background: rgba(0,0,0,0.16);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 12px;
                padding: 6px;
                color: rgba(230,238,248,0.92);
            }
            QListWidget#StatusList::item{
                padding: 0px;
                margin: 6px 2px;
                border-radius: 12px;
                background: rgba(255,255,255,0.06);
            }
            QListWidget#StatusList::item:selected{
                background: rgba(57,113,249,0.25);
                border: 1px solid rgba(57,113,249,0.45);
            }

            QLabel#StatusTitle{ color: rgba(230,238,248,0.95); font-weight: 900; font-size: 12px; }
            QLabel#StatusSub{ color: rgba(230,238,248,0.70); font-size: 11px; }

            QFrame#ChipsBox{
                background: rgba(0,0,0,0.14);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 12px;
            }
            QPushButton#Chip{
                background: rgba(57,113,249,0.18);
                border: 1px solid rgba(57,113,249,0.32);
                border-radius: 999px;
                padding: 6px 10px;
                color: rgba(230,238,248,0.92);
                font-weight: 800;
            }
            QPushButton#Chip:hover{
                background: rgba(57,113,249,0.26);
                border: 1px solid rgba(57,113,249,0.48);
            }

            QPushButton#OpenMiniBtn{
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.14);
                border-radius: 10px;
            }
            QPushButton#OpenMiniBtn:hover{ background: rgba(255,255,255,0.12); }

            QPushButton#PrimaryBtn{
                background: rgba(57,113,249,0.85);
                border: 1px solid rgba(57,113,249,0.95);
                border-radius: 10px;
                padding: 6px 12px;
                color: white;
                font-weight: 900;
            }
            QPushButton#PrimaryBtn:hover{ background: rgba(57,113,249,0.95); }

            QPushButton#SecondaryBtn{
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.14);
                border-radius: 10px;
                padding: 6px 10px;
                color: rgba(230,238,248,0.92);
                font-weight: 800;
            }
            QPushButton#SecondaryBtn:hover{ background: rgba(255,255,255,0.12); }

            QPushButton#DangerBtn{
                background: rgba(255,70,70,0.18);
                border: 1px solid rgba(255,70,70,0.35);
                border-radius: 10px;
                padding: 6px 10px;
                color: rgba(255,200,200,0.95);
                font-weight: 800;
            }
            QPushButton#DangerBtn:hover{ background: rgba(255,70,70,0.25); }
            """
        )

    # ---------------- model icons ----------------

    def _make_icon(self, model_id: str, icon_hint: Optional[str]) -> QIcon:
        if icon_hint:
            try:
                ic = QIcon(icon_hint)
                if not ic.isNull():
                    return ic
            except Exception:
                pass

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

        s = self.style()
        mid = (model_id or "").lower()
        if "gpt" in mid or "openai" in mid:
            return s.standardIcon(QStyle.SP_ComputerIcon)
        if "deepseek" in mid:
            return s.standardIcon(QStyle.SP_DriveNetIcon)
        return s.standardIcon(QStyle.SP_FileIcon)

    def _set_model_options(self, items: List[Tuple[str, str, Optional[str]]]):
        self.cmb_model.blockSignals(True)
        self.cmb_model.clear()
        self._model_icons.clear()

        for label, mid, icon_hint in items:
            ic = self._make_icon(mid, icon_hint)
            self._model_icons[mid] = ic
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
            self._selected_model_id = str(self.cmb_model.currentData() or "")

    def _on_combo_model_changed(self, idx: int):
        mid = str(self.cmb_model.currentData() or "").strip()
        if mid:
            self._selected_model_id = mid
            self._persist_inputs()

    # ---------------- persistence ----------------

    def _load_from_runtime(self):
        st = _rt_get()

        key = str(st.get("ai_api_key", "") or "")
        if key:
            self.edt_key.setText(key)

        cfg_models = _cfg_get("AI_REPLY_MODELS", "AI_MODELS", "OPENAI_MODELS", default=None)
        items = _normalize_models(cfg_models)
        if not items:
            items = [("gpt-5-mini（默认）", "gpt-5-mini", None)]
        self._set_model_options(items)

        saved_model = str(st.get("rewrite_model_id", "") or st.get("ai_model", "") or "")
        if not saved_model:
            saved_model = items[0][1]
        self._select_model_id(saved_model)

        # ✅ 原文不保存：每次打开都清空
        self.txt_input.setPlainText("")

        # ✅ 但可选项要保存并回填
        self.chk_extra.setChecked(bool(st.get("rewrite_extra_on", False)))
        self.txt_extra.setPlainText(str(st.get("rewrite_extra_text", "") or ""))

        self.chk_filter.setChecked(bool(st.get("rewrite_filter_on", False)))
        filt_words = []
        v = st.get("rewrite_filter_words", None)
        if isinstance(v, list):
            filt_words = [str(x).strip() for x in v if str(x).strip()]
        self.filter_chips.set_words(filt_words)

        mode = str(st.get("rewrite_mode", "quick") or "quick")
        if mode == "deep":
            self.btn_deep.setChecked(True)
        else:
            self.btn_quick.setChecked(True)

        self._on_input_changed()


    def _persist_inputs(self):
        # ✅ 保存：可选项（附加要求/过滤关键词/模式/模型选择）
        # ❌ 不保存：原文（每次运行都是新的原文）
        _rt_set("rewrite_extra_on", bool(self.chk_extra.isChecked()))
        _rt_set("rewrite_extra_text", self.txt_extra.toPlainText())
        _rt_set("rewrite_filter_on", bool(self.chk_filter.isChecked()))
        _rt_set("rewrite_filter_words", self.filter_chips.words())
        _rt_set("rewrite_mode", "deep" if self.btn_deep.isChecked() else "quick")

        mid = (self._selected_model_id or "").strip()
        if mid:
            _rt_set("rewrite_model_id", mid)


    # ---------------- UI callbacks ----------------

    def _on_input_changed(self):
        txt = self.txt_input.toPlainText() or ""
        self.lbl_count.setText(f"{len(txt)} 字")
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
            confirm_dialog(self, "提示", "请先输入 API Key")
            return
        _rt_set("ai_api_key", key)
        confirm_dialog(self, "保存成功", "API Key 已保存（runtime_state.json）")

    def save_model(self):
        mid = (self._selected_model_id or "").strip()
        if not mid:
            confirm_dialog(self, "提示", "请选择一个模型")
            return
        _rt_set("rewrite_model_id", mid)
        confirm_dialog(self, "保存成功", f"话术改写默认模型：{mid}")

    def open_rewrite_dir(self):
        p = _rewrite_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    # ---------------- status/history ----------------

    def _get_history(self) -> List[dict]:
        st = _rt_get()
        hist = st.get("rewrite_history", [])
        if isinstance(hist, list):
            return [x for x in hist if isinstance(x, dict)]
        return []

    def _set_history(self, hist: List[dict]):
        _rt_set("rewrite_history", hist)

    def _append_history(self, item: dict):
        hist = self._get_history()
        hist.insert(0, item)
        hist = hist[:60]
        self._set_history(hist)

    def _open_record(self, rec: dict):
        path = str((rec or {}).get("path", "") or "").strip()
        if not path:
            confirm_dialog(self, "无法打开", "该记录没有文件路径。")
            return
        if not os.path.exists(path):
            confirm_dialog(self, "文件不存在", f"文件不存在：\n{path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _reload_history_list(self):
        self.list_status.clear()
        hist = self._get_history()
        ok_hist = [x for x in hist if bool(x.get("ok", False)) and str(x.get("path", "") or "").strip()]

        for rec in ok_hist:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, rec)
            item.setSizeHint(QSize(0, 52))
            self.list_status.addItem(item)

            w = StatusItemWidget(rec, open_cb=self._open_record)
            self.list_status.setItemWidget(item, w)

    def _open_selected_item(self):
        item = self.list_status.currentItem()
        if not item:
            return
        rec = item.data(Qt.UserRole) or {}
        self._open_record(rec)

    def clear_history(self):
        self._set_history([])
        self._reload_history_list()
        self.txt_log.setPlainText("已清空记录。")

    # ---------------- submit ----------------

    def submit(self):
        api_key = (self.edt_key.text() or "").strip()
        if not api_key:
            confirm_dialog(self, "提示", "请先输入并保存 API Key。")
            return

        text = (self.txt_input.toPlainText() or "").strip()
        if not text:
            confirm_dialog(self, "提示", "请先输入要改写的原文。")
            return

        model_id = (self._selected_model_id or "").strip()
        if not model_id:
            model_id = str(self.cmb_model.currentData() or "").strip()
        if not model_id:
            confirm_dialog(self, "提示", "请选择一个模型。")
            return

        mode = "deep" if self.btn_deep.isChecked() else "quick"

        extra_on = bool(self.chk_extra.isChecked())
        extra = (self.txt_extra.toPlainText() or "").strip()
        if not extra_on:
            extra = ""

        filt_on = bool(self.chk_filter.isChecked())
        filt_words = self.filter_chips.words()
        if not filt_on:
            filt_words = []

        host = str(_cfg_get("AI_API_HOST", "API_HOST", default="ai.zhimengai.xyz") or "ai.zhimengai.xyz").strip()
        path = str(_cfg_get("AI_API_PATH", "API_PATH", default="/v1/chat/completions") or "/v1/chat/completions").strip()
        if not path.startswith("/"):
            path = "/" + path

        self._persist_inputs()

        self.btn_submit.setEnabled(False)
        self.btn_submit.setText("提交中…")
        self.txt_log.setPlainText(
            f"准备提交…\n"
            f"请求：https://{host}{path}\n"
            f"模型：{model_id}\n"
            f"模式：{mode}\n"
            f"原文字数：{len(text)}\n"
            f"附加要求：{'提交' if extra_on else '不提交'}\n"
            f"过滤关键词：{'提交' if (filt_on and filt_words) else '不提交'}\n"
        )

        self._thread = QThread(self)
        self._worker = _RewriteWorker(
            api_key=api_key, model=model_id, mode=mode, text=text,
            extra_on=extra_on, extra=extra,
            filt_on=filt_on, filt_words=filt_words,
            host=host, path=path
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_finished(self, ok: bool, payload: dict):
        try:
            elapsed = int(payload.get("elapsed_ms", 0) or 0)
            model = str(payload.get("model", "") or "")
            mode = str(payload.get("mode", "") or "")
            err = str(payload.get("error", "") or "")
            result_text = str(payload.get("result_text", "") or "")
            finish_reason = str(payload.get("finish_reason", "") or "")
            usage = payload.get("usage", {}) or {}
            tries = int(payload.get("tries", 0) or 0)
            input_chars = int(payload.get("input_chars", 0) or 0)
            output_chars = int(payload.get("output_chars", 0) or 0)
            debug = payload.get("debug", []) or []
            raw_list = payload.get("raw_list", []) or []

            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            file_path = ""

            if ok and result_text:
                head = (self.txt_input.toPlainText() or "").strip().splitlines()[0] if (self.txt_input.toPlainText() or "").strip() else "话术"
                head = _safe_filename(head)
                stamp = time.strftime("%Y%m%d_%H%M%S")
                fname = f"{stamp}_{'快速' if mode == 'quick' else '深度'}_{head}.txt"
                out_path = _rewrite_dir() / fname

                # ✅ 不保存原文：只写元信息 + 改写结果
                meta = [
                    f"生成时间：{ts}",
                    f"模式：{'快速改写' if mode == 'quick' else '深度改写'}",
                    f"模型：{model}",
                    f"耗时：{elapsed} ms",
                    f"续写次数：{tries}",
                    f"finish_reason：{finish_reason}",
                    f"usage：{usage}",
                    f"原文字数：{input_chars}",
                    f"输出字数：{len(result_text)}",
                    "",
                    "==================== 改写结果 ====================",
                    result_text.strip(),
                ]
                out_path.write_text("\n".join(meta), encoding="utf-8")
                file_path = str(out_path)

                log_lines = [
                    "✅ 生成成功",
                    f"时间：{ts}",
                    f"模式：{mode}",
                    f"模型：{model}",
                    f"耗时：{elapsed} ms",
                    f"续写次数：{tries}",
                    f"finish_reason：{finish_reason}",
                    f"usage：{usage}",
                    f"原文字数：{input_chars}",
                    f"输出字数：{len(result_text)}",
                    f"保存：{file_path}",
                    "",
                    "调试信息：",
                ]
                for d in debug[-10:]:
                    log_lines.append(f" - {d}")
                if raw_list:
                    log_lines.append("")
                    log_lines.append("原始返回片段（每轮前 3000 字符）：")
                    for idx, r in enumerate(raw_list, 1):
                        log_lines.append(f"[try#{idx}] {r[:800]}")  # 日志别太长
                self.txt_log.setPlainText("\n".join(log_lines))

                # ✅ 只记录成功
                rec = {
                    "time": ts,
                    "ok": True,
                    "mode": "快速改写" if mode == "quick" else "深度改写",
                    "model": model,
                    "path": file_path,
                    "elapsed_ms": elapsed,
                }
                self._append_history(rec)
                self._reload_history_list()

                # ✅ 完成后询问是否打开（Yes/No）
                ret = QMessageBox.question(
                    self,
                    "生成完成",
                    "已生成并保存到“话术改写”目录。\n\n是否立即打开文本？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                if ret == QMessageBox.Yes:
                    self._open_record(rec)

            else:
                # 失败不记录
                log_lines = [
                    "❌ 生成失败（不会记录到任务状态）",
                    f"时间：{ts}",
                    f"模式：{mode}",
                    f"模型：{model}",
                    f"耗时：{elapsed} ms",
                    f"续写次数：{tries}",
                    f"finish_reason：{finish_reason}",
                    f"usage：{usage}",
                    f"原文字数：{input_chars}",
                    f"输出字数：{output_chars}",
                    f"原因：{err or '未知错误'}",
                ]
                for d in debug[-10:]:
                    log_lines.append(f" - {d}")
                if raw_list:
                    log_lines.append("")
                    log_lines.append("原始返回片段（每轮前 3000 字符）：")
                    for idx, r in enumerate(raw_list, 1):
                        log_lines.append(f"[try#{idx}] {r[:1200]}")
                self.txt_log.setPlainText("\n".join(log_lines))

                confirm_dialog(self, "失败", "改写失败，详情见任务日志。")

        finally:
            self.btn_submit.setEnabled(True)
            self.btn_submit.setText("提交改写")
