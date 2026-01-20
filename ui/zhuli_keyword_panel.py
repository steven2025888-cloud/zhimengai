from __future__ import annotations

import json
from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox,
    QFileDialog, QMessageBox
)

from core.zhuli_keyword_io import load_zhuli_keywords, save_zhuli_keywords


def _lines_to_list(text: str) -> list[str]:
    items = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s:
            items.append(s)
    return items


def _list_to_lines(items: list[str]) -> str:
    return "\n".join([str(x) for x in (items or [])])


class ZhuliKeywordPanel(QWidget):
    """助播关键词管理：只配置匹配条件，不配置回复文本。"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.data: Dict[str, dict] = {}
        self._current_key: str | None = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # 左：分类列表
        left = QVBoxLayout()
        root.addLayout(left, 3)

        self.list = QListWidget()
        self.list.setMinimumWidth(220)
        left.addWidget(self.list, 1)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("➕ 新增")
        self.btn_del = QPushButton("🗑 删除")
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_del)
        left.addLayout(btn_row)

        io_row = QHBoxLayout()
        self.btn_import = QPushButton("📥 导入")
        self.btn_export = QPushButton("📤 导出")
        self.btn_save = QPushButton("💾 保存")
        io_row.addWidget(self.btn_import)
        io_row.addWidget(self.btn_export)
        io_row.addWidget(self.btn_save)
        left.addLayout(io_row)

        # 右：编辑区
        right = QVBoxLayout()
        root.addLayout(right, 7)

        title = QLabel("助播关键词编辑")
        title.setStyleSheet("font-size:14px;font-weight:800;")
        right.addWidget(title)

        self.ed_prefix = QLineEdit()
        self.ed_prefix.setPlaceholderText("分类名 / prefix（用于匹配 zhuli_audio 文件前缀）")
        right.addWidget(self._row("Prefix", self.ed_prefix))

        self.sp_priority = QSpinBox()
        self.sp_priority.setRange(-999, 999)
        right.addWidget(self._row("Priority", self.sp_priority))

        self.ed_must = QPlainTextEdit()
        self.ed_must.setPlaceholderText("must：必须包含（每行一个）")
        right.addWidget(self._block("must", self.ed_must))

        self.ed_any = QPlainTextEdit()
        self.ed_any.setPlaceholderText("any：任意包含（每行一个）")
        right.addWidget(self._block("any", self.ed_any))

        self.ed_deny = QPlainTextEdit()
        self.ed_deny.setPlaceholderText("deny：禁止包含（每行一个）")
        right.addWidget(self._block("deny", self.ed_deny))

        right.addStretch(1)

        # signals
        self.list.currentRowChanged.connect(self._on_select)
        self.btn_add.clicked.connect(self._add)
        self.btn_del.clicked.connect(self._delete)
        self.btn_save.clicked.connect(self._save)
        self.btn_import.clicked.connect(self._import)
        self.btn_export.clicked.connect(self._export)

        self.reload()

    def _row(self, label: str, widget: QWidget) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        lab = QLabel(label)
        lab.setFixedWidth(70)
        h.addWidget(lab)
        h.addWidget(widget, 1)
        return w

    def _block(self, label: str, editor: QPlainTextEdit) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        lab = QLabel(label)
        lab.setStyleSheet("color:#93A4B7;")
        v.addWidget(lab)
        v.addWidget(editor, 1)
        return w

    # ===================== data =====================

    def reload(self):
        self.data = load_zhuli_keywords()
        self.list.clear()
        for k in sorted(self.data.keys()):
            self.list.addItem(QListWidgetItem(k))
        if self.list.count() > 0:
            self.list.setCurrentRow(0)
        else:
            self._current_key = None

    def _on_select(self, idx: int):
        if idx < 0:
            self._current_key = None
            return
        key = self.list.item(idx).text()
        self._current_key = key
        item = self.data.get(key, {})
        self.ed_prefix.setText(str(item.get("prefix", key) or key))
        self.sp_priority.setValue(int(item.get("priority", 0) or 0))
        self.ed_must.setPlainText(_list_to_lines(item.get("must", []) or []))
        self.ed_any.setPlainText(_list_to_lines(item.get("any", []) or []))
        self.ed_deny.setPlainText(_list_to_lines(item.get("deny", []) or []))

    def _collect_form(self) -> dict:
        prefix = (self.ed_prefix.text() or "").strip()
        if not prefix:
            raise ValueError("Prefix 不能为空")
        return {
            "priority": int(self.sp_priority.value()),
            "must": _lines_to_list(self.ed_must.toPlainText()),
            "any": _lines_to_list(self.ed_any.toPlainText()),
            "deny": _lines_to_list(self.ed_deny.toPlainText()),
            "prefix": prefix,
        }

    def _add(self):
        base = "新分类"
        name = base
        i = 1
        while name in self.data:
            i += 1
            name = f"{base}{i}"
        self.data[name] = {"priority": 0, "must": [], "any": [], "deny": [], "prefix": name}
        self.list.addItem(QListWidgetItem(name))
        self.list.setCurrentRow(self.list.count() - 1)

    def _delete(self):
        key = self._current_key
        if not key:
            return
        if QMessageBox.question(self, "确认删除", f"确定删除：{key} ?") != QMessageBox.Yes:
            return
        self.data.pop(key, None)
        self.reload()

    def _save(self):
        key = self._current_key
        if not key:
            QMessageBox.information(self, "提示", "请先选择一个分类")
            return
        try:
            item = self._collect_form()
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return

        # 如果用户修改了 prefix/分类名，允许改 key
        new_key = item.get("prefix")
        if new_key != key:
            # 防止覆盖
            if new_key in self.data and new_key != key:
                QMessageBox.warning(self, "保存失败", f"已存在同名分类：{new_key}")
                return
            self.data.pop(key, None)
            self.data[new_key] = item
        else:
            self.data[key] = item

        save_zhuli_keywords(self.data)
        self.reload()
        # 重新选中
        for i in range(self.list.count()):
            if self.list.item(i).text() == new_key:
                self.list.setCurrentRow(i)
                break
        QMessageBox.information(self, "保存成功", "助播关键词已保存")

    def _import(self):
        fp, _ = QFileDialog.getOpenFileName(self, "导入助播关键词", "", "JSON (*.json);;All (*.*)")
        if not fp:
            return
        try:
            with open(fp, "r", encoding="utf-8") as f:
                incoming = json.load(f)
            if not isinstance(incoming, dict):
                raise ValueError("导入文件必须是 dict")
            # merge
            for k, v in incoming.items():
                if isinstance(v, dict):
                    self.data[k] = v
            save_zhuli_keywords(self.data)
            self.reload()
            QMessageBox.information(self, "导入成功", "已导入并保存")
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))

    def _export(self):
        fp, _ = QFileDialog.getSaveFileName(self, "导出助播关键词", "zhuli_keywords.json", "JSON (*.json)")
        if not fp:
            return
        try:
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
            QMessageBox.information(self, "导出成功", fp)
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))
