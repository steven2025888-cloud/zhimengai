from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QLineEdit
)
from PySide6.QtCore import Qt


class ConfirmDialog(QDialog):
    def __init__(self, parent, title: str, text: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._ok = False

        root = QVBoxLayout(self)
        root.setSpacing(12)

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-size: 13px; color: #E6EEF8;")
        root.addWidget(lbl)

        row = QHBoxLayout()
        row.addStretch(1)

        btn_cancel = QPushButton("取消")
        btn_ok = QPushButton("确认")
        btn_cancel.setFixedHeight(34)
        btn_ok.setFixedHeight(34)

        btn_cancel.clicked.connect(self._cancel)
        btn_ok.clicked.connect(self._confirm)

        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)
        root.addLayout(row)

    def _confirm(self):
        self._ok = True
        self.accept()

    def _cancel(self):
        self._ok = False
        self.reject()

    @property
    def ok(self) -> bool:
        return self._ok


def confirm_dialog(parent, title: str, text: str) -> bool:
    dlg = ConfirmDialog(parent, title, text)
    dlg.exec()
    return dlg.ok


class TextInputDialog(QDialog):
    def __init__(self, parent, title: str, label: str, default: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._ok = False
        self._value = ""

        root = QVBoxLayout(self)
        root.setSpacing(10)

        lbl = QLabel(label)
        lbl.setWordWrap(True)
        root.addWidget(lbl)

        self.input = QLineEdit()
        self.input.setText(default)
        root.addWidget(self.input)

        row = QHBoxLayout()
        row.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_ok = QPushButton("确认")
        btn_cancel.setFixedHeight(34)
        btn_ok.setFixedHeight(34)
        btn_cancel.clicked.connect(self._cancel)
        btn_ok.clicked.connect(self._confirm)
        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)
        root.addLayout(row)

    def _confirm(self):
        self._ok = True
        self._value = self.input.text().strip()
        self.accept()

    def _cancel(self):
        self._ok = False
        self.reject()

    @property
    def ok(self) -> bool:
        return self._ok

    @property
    def value(self) -> str:
        return self._value


class MultiLineInputDialog(QDialog):
    def __init__(self, parent, title: str, label: str, default: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._ok = False
        self._text = ""

        root = QVBoxLayout(self)
        root.setSpacing(10)

        lbl = QLabel(label)
        lbl.setWordWrap(True)
        root.addWidget(lbl)

        self.edit = QTextEdit()
        self.edit.setPlainText(default)
        self.edit.setMinimumHeight(220)
        root.addWidget(self.edit)

        row = QHBoxLayout()
        row.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_ok = QPushButton("确认")
        btn_cancel.setFixedHeight(34)
        btn_ok.setFixedHeight(34)
        btn_cancel.clicked.connect(self._cancel)
        btn_ok.clicked.connect(self._confirm)
        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)
        root.addLayout(row)

    def _confirm(self):
        self._ok = True
        self._text = self.edit.toPlainText()
        self.accept()

    def _cancel(self):
        self._ok = False
        self.reject()

    @property
    def ok(self) -> bool:
        return self._ok

    @property
    def text(self) -> str:
        return self._text
