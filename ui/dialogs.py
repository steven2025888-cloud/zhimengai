# ui/dialogs.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QLineEdit,
    QSpinBox, QWidget, QSizePolicy
)


# ========= 统一暗色弹窗样式（不吃你 AppBackground 的全局染色） =========
DIALOG_QSS = """
QDialog {
    background: #1F2329;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 14px;
}
QLabel {
    color: #E6EEF8;
    font-size: 13px;
}
QLabel#DialogTitle {
    font-size: 15px;
    font-weight: 900;
    color: #EAF2FF;
}
QLabel#DialogSub {
    color: rgba(233,236,245,0.70);
}
QWidget#Divider {
    background: rgba(255,255,255,0.08);
    min-height: 1px;
    max-height: 1px;
}
QLineEdit, QTextEdit, QSpinBox {
    background: #0F1A2E;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 10px;
    padding: 8px 10px;
    color: #EAF2FF;
    selection-background-color: rgba(57,113,249,0.35);
}
QTextEdit {
    padding: 10px 12px;
}
QPushButton {
    border-radius: 10px;
    padding: 8px 14px;
    font-weight: 800;
    min-height: 34px;
}
QPushButton#BtnPrimary {
    background: #3971f9;
    color: #FFFFFF;
}
QPushButton#BtnPrimary:hover { background: rgba(57,113,249,0.85); }
QPushButton#BtnPrimary:pressed { background: rgba(57,113,249,0.65); }

QPushButton#BtnGhost {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.10);
    color: #E6EEF8;
}
QPushButton#BtnGhost:hover { background: rgba(255,255,255,0.10); }
QPushButton#BtnGhost:pressed { background: rgba(255,255,255,0.06); }
"""


def _divider() -> QWidget:
    w = QWidget()
    w.setObjectName("Divider")
    w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    w.setFixedHeight(1)
    return w


class BaseDialog(QDialog):
    """统一的弹窗基类：自动套用样式、统一间距、统一按钮区。"""

    def __init__(self, parent=None, title: str = "", subtitle: str = ""):
        super().__init__(parent)
        self.setModal(True)
        self.setStyleSheet(DIALOG_QSS)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._ok = False

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(16, 16, 16, 14)
        self.root.setSpacing(10)

        # Header
        if title:
            t = QLabel(title)
            t.setObjectName("DialogTitle")
            t.setWordWrap(True)
            self.root.addWidget(t)

        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("DialogSub")
            s.setWordWrap(True)
            self.root.addWidget(s)

        self.root.addWidget(_divider())

        # Body container
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        self.root.addLayout(self.body)

        # Footer
        self.root.addWidget(_divider())
        self.footer = QHBoxLayout()
        self.footer.setSpacing(10)
        self.footer.addStretch(1)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("BtnGhost")
        self.btn_ok = QPushButton("确认")
        self.btn_ok.setObjectName("BtnPrimary")

        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_ok.clicked.connect(self._confirm)

        self.footer.addWidget(self.btn_cancel)
        self.footer.addWidget(self.btn_ok)
        self.root.addLayout(self.footer)

        self.setMinimumWidth(420)

    def _confirm(self):
        self._ok = True
        self.accept()

    def _cancel(self):
        self._ok = False
        self.reject()

    @property
    def ok(self) -> bool:
        return self._ok


# ===================== 1) 确认/提示 =====================

class ConfirmDialog(BaseDialog):
    def __init__(self, parent, title: str, text: str, subtitle: str = ""):
        super().__init__(parent, title=title, subtitle=subtitle)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        self.body.addWidget(lbl)


def confirm_dialog(parent, title: str, text: str, subtitle: str = "") -> bool:
    dlg = ConfirmDialog(parent, title, text, subtitle=subtitle)
    dlg.exec()
    return dlg.ok


# ===================== 2) 单行输入 =====================

class TextInputDialog(BaseDialog):
    def __init__(self, parent, title: str, label: str, default: str = "",
                 placeholder: str = "", max_len: int = 0):
        super().__init__(parent, title=title)
        lbl = QLabel(label)
        lbl.setWordWrap(True)
        self.body.addWidget(lbl)

        self.input = QLineEdit()
        self.input.setText(default or "")
        if placeholder:
            self.input.setPlaceholderText(placeholder)
        if max_len and max_len > 0:
            self.input.setMaxLength(max_len)
        self.body.addWidget(self.input)

        self.input.returnPressed.connect(self._confirm)
        self._value = ""

    def _confirm(self):
        self._value = (self.input.text() or "").strip()
        super()._confirm()

    @property
    def value(self) -> str:
        return self._value


def text_input_dialog(parent, title: str, label: str, default: str = "",
                      placeholder: str = "", max_len: int = 0) -> Tuple[str, bool]:
    dlg = TextInputDialog(parent, title, label, default=default, placeholder=placeholder, max_len=max_len)
    dlg.exec()
    return dlg.value, dlg.ok


# ===================== 3) 数字输入（替代 QInputDialog.getInt） =====================

class IntInputDialog(BaseDialog):
    def __init__(self, parent, title: str, label: str,
                 value: int = 0, min_value: int = 0, max_value: int = 999999, step: int = 1):
        super().__init__(parent, title=title)
        lbl = QLabel(label)
        lbl.setWordWrap(True)
        self.body.addWidget(lbl)

        self.spin = QSpinBox()
        self.spin.setRange(min_value, max_value)
        self.spin.setSingleStep(step)
        self.spin.setValue(value)
        self.body.addWidget(self.spin)

        self._value = value

    def _confirm(self):
        self._value = int(self.spin.value())
        super()._confirm()

    @property
    def value(self) -> int:
        return self._value


def int_input_dialog(parent, title: str, label: str,
                     value: int = 0, min_value: int = 0, max_value: int = 999999, step: int = 1) -> Tuple[int, bool]:
    dlg = IntInputDialog(parent, title, label, value=value, min_value=min_value, max_value=max_value, step=step)
    dlg.exec()
    return dlg.value, dlg.ok


# ===================== 4) 多行输入 =====================

class MultiLineInputDialog(BaseDialog):
    def __init__(self, parent, title: str, label: str, default: str = ""):
        super().__init__(parent, title=title)
        lbl = QLabel(label)
        lbl.setWordWrap(True)
        self.body.addWidget(lbl)

        self.edit = QTextEdit()
        self.edit.setPlainText(default or "")
        self.edit.setMinimumHeight(220)
        self.body.addWidget(self.edit)

        self._text = ""

    def _confirm(self):
        self._text = self.edit.toPlainText()
        super()._confirm()

    @property
    def text(self) -> str:
        return self._text


def multiline_input_dialog(parent, title: str, label: str, default: str = "") -> Tuple[str, bool]:
    dlg = MultiLineInputDialog(parent, title, label, default=default)
    dlg.exec()
    return dlg.text, dlg.ok


# ===================== 5) 三选一/多选一（替代 QMessageBox.addButton 那套） =====================

@dataclass
class ChoiceItem:
    text: str
    role: str = "normal"  # normal / destructive / cancel


class ChoiceDialog(BaseDialog):
    def __init__(self, parent, title: str, text: str, items: List[ChoiceItem]):
        super().__init__(parent, title=title)
        self._choice: Optional[str] = None

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        self.body.addWidget(lbl)

        # 覆盖 footer：用多个按钮代替“取消/确认”
        # 这里把基类按钮隐藏掉
        self.btn_cancel.hide()
        self.btn_ok.hide()

        # 清空 footer，重新布局
        while self.footer.count():
            it = self.footer.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

        self.footer.addStretch(1)

        for item in items:
            b = QPushButton(item.text)
            if item.role == "cancel":
                b.setObjectName("BtnGhost")
                b.clicked.connect(self._cancel)
            elif item.role == "destructive":
                # 用主按钮样式但你也可以改成红色；先保持统一风格
                b.setObjectName("BtnPrimary")
                b.clicked.connect(lambda _=False, t=item.text: self._pick(t))
            else:
                b.setObjectName("BtnGhost")
                b.clicked.connect(lambda _=False, t=item.text: self._pick(t))
            self.footer.addWidget(b)

    def _pick(self, text: str):
        self._choice = text
        self._ok = True
        self.accept()

    @property
    def choice(self) -> Optional[str]:
        return self._choice


def choice_dialog(parent, title: str, text: str, items: List[ChoiceItem]) -> Tuple[Optional[str], bool]:
    dlg = ChoiceDialog(parent, title, text, items)
    dlg.exec()
    return dlg.choice, dlg.ok
