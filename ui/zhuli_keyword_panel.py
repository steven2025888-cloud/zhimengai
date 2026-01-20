from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QTabWidget, QPushButton,
    QFileDialog, QAbstractItemView, QMessageBox, QSpinBox, QInputDialog
)

from core.zhuli_keyword_io import load_zhuli_keywords, save_zhuli_keywords, merge_zhuli_keywords

# 尽量复用你项目里的对话框（样式一致）。没有的话就降级用系统对话框。
try:
    from ui.dialogs import confirm_dialog, TextInputDialog, MultiLineInputDialog
except Exception:  # pragma: no cover
    confirm_dialog = None
    TextInputDialog = None
    MultiLineInputDialog = None


def _split_words(raw: str) -> List[str]:
    """支持：换行 / 英文逗号 / 中文逗号 / 分号"""
    parts = re.split(r"[\n,，;；]+", raw or "")
    return [p.strip() for p in parts if p.strip()]


def _dedup_keep_order(words: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for w in words:
        w = str(w).strip()
        if not w:
            continue
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


def _guess_prefix_from_filename(filename: str) -> str:
    """从文件名猜测分类前缀：优先取 '_' 或 '-' 或空格 之前的部分。"""
    name = os.path.splitext(os.path.basename(filename))[0]
    for sep in ("_", "-", " "):
        if sep in name:
            name = name.split(sep, 1)[0]
            break
    return (name or "").strip()


def _get_zhuli_audio_dir() -> Path:
    """严格按 config.ZHULI_AUDIO_DIR（exe 同级 zhuli_audio）。"""
    try:
        from config import ZHULI_AUDIO_DIR
        # 你的 config 里 ZHULI_AUDIO_DIR 是 Path（见你发的 config.py）
        return Path(ZHULI_AUDIO_DIR)
    except Exception:
        return Path.cwd() / "zhuli_audio"


def _get_supported_exts() -> Tuple[str, ...]:
    try:
        from config import SUPPORTED_AUDIO_EXTS
        return tuple(SUPPORTED_AUDIO_EXTS)
    except Exception:
        return (".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg")


class ZhuliKeywordPanel(QWidget):
    """助播关键词管理（UI 按你发的 KeywordPanel 布局风格重做）。"""

    # ✅实时变更信号：外部可监听，立刻更新运行内存（不落盘）
    sig_realtime_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.data: Dict[str, dict] = load_zhuli_keywords()
        self.current_prefix: str | None = None
        self.new_added_prefixes: set[str] = set()

        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ===== 顶部栏 =====
        header = QHBoxLayout()
        title = QLabel("助播关键词管理")
        title.setStyleSheet("font-size: 16px; font-weight: 800;")
        header.addWidget(title)
        header.addStretch(1)

        self.btn_export = QPushButton("导出")
        self.btn_import = QPushButton("导入（合并）")
        self.btn_save = QPushButton("保存")

        for b in (self.btn_export, self.btn_import, self.btn_save):
            b.setFixedHeight(36)

        header.addWidget(self.btn_export)
        header.addWidget(self.btn_import)
        header.addWidget(self.btn_save)
        root.addLayout(header)

        # ===== 主体 =====
        body = QHBoxLayout()
        body.setSpacing(10)
        root.addLayout(body, 1)

        # ===== 左侧：分类列表 =====
        left = QVBoxLayout()
        body.addLayout(left, 2)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索分类（前缀）…")
        self.search.textChanged.connect(self.refresh_prefix_list)
        left.addWidget(self.search)

        self.prefix_list = QListWidget()
        self.prefix_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.prefix_list.itemSelectionChanged.connect(self.on_select_prefix)
        left.addWidget(self.prefix_list, 1)

        left_ops = QHBoxLayout()
        self.btn_add_prefix = QPushButton("新建分类")
        self.btn_rename_prefix = QPushButton("重命名")
        self.btn_del_prefix = QPushButton("删除分类")
        for b in (self.btn_add_prefix, self.btn_rename_prefix, self.btn_del_prefix):
            b.setFixedHeight(34)
        left_ops.addWidget(self.btn_add_prefix)
        left_ops.addWidget(self.btn_rename_prefix)
        left_ops.addWidget(self.btn_del_prefix)
        left.addLayout(left_ops)

        self.btn_scan_dir = QPushButton("检查目录（zhuli_audio）")
        self.btn_scan_dir.setFixedHeight(34)
        self.btn_scan_dir.setToolTip("按 config.ZHULI_AUDIO_DIR 扫描音频文件名，自动识别前缀并提示是否保存为分类")
        left.addWidget(self.btn_scan_dir)

        # ===== 右侧：词库 =====
        right = QVBoxLayout()
        body.addLayout(right, 5)

        # 当前分类行 + 优先级
        current_row = QHBoxLayout()
        self.lbl_current = QLabel("当前分类：-")
        self.lbl_current.setStyleSheet("font-size: 14px; font-weight: 700;")
        current_row.addWidget(self.lbl_current)
        current_row.addStretch(1)

        pr_lab = QLabel("优先级")
        pr_lab.setStyleSheet("color:#93A4B7;")
        self.sp_priority = QSpinBox()
        self.sp_priority.setRange(-999, 999)
        self.sp_priority.setFixedWidth(90)
        self.sp_priority.setToolTip("优先级越大越优先（这里改动=实时生效；是否落盘由“保存”决定）")
        current_row.addWidget(pr_lab)
        current_row.addWidget(self.sp_priority)

        right.addLayout(current_row)

        # Tab
        self.tabs = QTabWidget()
        right.addWidget(self.tabs, 1)

        self.must_list = QListWidget()
        self.any_list = QListWidget()
        self.deny_list = QListWidget()

        for lst in (self.must_list, self.any_list, self.deny_list):
            lst.setSelectionMode(QAbstractItemView.ExtendedSelection)

        self.tabs.addTab(self.must_list, "必含词（0）")
        self.tabs.addTab(self.any_list, "意图词（0）")
        self.tabs.addTab(self.deny_list, "排除词（0）")

        # 操作区
        ops = QHBoxLayout()
        self.btn_batch_add = QPushButton("批量添加")
        self.btn_del_selected = QPushButton("删除选中")
        self.btn_clear_tab = QPushButton("清空当前页")
        self.btn_clear_prefix = QPushButton("清空本分类")

        for b in (self.btn_batch_add, self.btn_del_selected, self.btn_clear_tab, self.btn_clear_prefix):
            b.setFixedHeight(34)

        ops.addWidget(self.btn_batch_add)
        ops.addWidget(self.btn_del_selected)
        ops.addWidget(self.btn_clear_tab)
        ops.addWidget(self.btn_clear_prefix)
        ops.addStretch(1)
        right.addLayout(ops)

        # ===== 绑定 =====
        self.btn_add_prefix.clicked.connect(self.add_prefix)
        self.btn_rename_prefix.clicked.connect(self.rename_prefix)
        self.btn_del_prefix.clicked.connect(self.delete_prefix)

        self.btn_batch_add.clicked.connect(self.batch_add_words)
        self.btn_del_selected.clicked.connect(self.delete_selected_words)
        self.btn_clear_tab.clicked.connect(self.clear_current_tab)
        self.btn_clear_prefix.clicked.connect(self.clear_current_prefix)

        self.btn_export.clicked.connect(self.export_json)
        self.btn_import.clicked.connect(self.import_merge_json)
        self.btn_save.clicked.connect(self.save_all)

        self.btn_scan_dir.clicked.connect(self.scan_zhuli_audio_dir)

        # ✅实时更新（不保存）：你一调优先级，运行时立刻生效
        self.sp_priority.valueChanged.connect(self._realtime_update_priority)

        # 初始加载
        self.refresh_prefix_list()

    # ===================== 左侧分类 =====================
    def refresh_prefix_list(self):
        keyword = (self.search.text() or "").strip()
        keep = self.current_prefix

        self.prefix_list.blockSignals(True)
        self.prefix_list.clear()

        all_prefixes = list(self.data.keys())
        normal = [p for p in all_prefixes if p not in self.new_added_prefixes]
        new = [p for p in all_prefixes if p in self.new_added_prefixes]
        prefixes = sorted(normal) + sorted(new)

        for p in prefixes:
            if keyword and keyword not in p:
                continue
            show_name = p + "（新）" if p in self.new_added_prefixes else p
            item = QListWidgetItem(show_name)
            item.setData(Qt.UserRole, p)
            self.prefix_list.addItem(item)

        self.prefix_list.blockSignals(False)

        # 尽量保持原选中
        if keep:
            for i in range(self.prefix_list.count()):
                if self.prefix_list.item(i).data(Qt.UserRole) == keep:
                    self.prefix_list.setCurrentRow(i)
                    return

        if self.prefix_list.count() > 0:
            self.prefix_list.setCurrentRow(0)
        else:
            self.current_prefix = None
            self.lbl_current.setText("当前分类：-")
            self.must_list.clear()
            self.any_list.clear()
            self.deny_list.clear()
            self._update_tab_counts_empty()

    def on_select_prefix(self):
        items = self.prefix_list.selectedItems()
        if not items:
            return
        prefix = items[0].data(Qt.UserRole)

        self.current_prefix = prefix
        self.lbl_current.setText(f"当前分类：{prefix}")
        self._render_prefix(prefix)

    def add_prefix(self):
        name = None

        if TextInputDialog is not None:
            dlg = TextInputDialog(self, "新建分类", "请输入分类名（例如：炉膛 / 尺寸 / 售后）：")
            dlg.exec()
            if not getattr(dlg, "ok", False) or not getattr(dlg, "value", ""):
                return
            name = str(dlg.value).strip()
        else:
            name, ok = QInputDialog.getText(self, "新建分类", "请输入分类名：")
            if not ok:
                return
            name = (name or "").strip()

        if not name:
            return
        if name in self.data:
            return

        self.data[name] = {"priority": 0, "must": [], "any": [], "deny": [], "prefix": name}
        self.new_added_prefixes.add(name)
        self.refresh_prefix_list()

        # 选中它
        for i in range(self.prefix_list.count()):
            if self.prefix_list.item(i).data(Qt.UserRole) == name:
                self.prefix_list.setCurrentRow(i)
                break

    def rename_prefix(self):
        if not self.current_prefix:
            return

        new_name = None
        if TextInputDialog is not None:
            dlg = TextInputDialog(self, "重命名分类", "请输入新分类名：", default=self.current_prefix)
            dlg.exec()
            if not getattr(dlg, "ok", False) or not getattr(dlg, "value", ""):
                return
            new_name = str(dlg.value).strip()
        else:
            new_name, ok = QInputDialog.getText(self, "重命名分类", "请输入新分类名：", text=self.current_prefix)
            if not ok:
                return
            new_name = (new_name or "").strip()

        if not new_name or new_name == self.current_prefix:
            return
        if new_name in self.data:
            return

        cfg = self.data.pop(self.current_prefix)
        cfg["prefix"] = new_name
        self.data[new_name] = cfg

        if self.current_prefix in self.new_added_prefixes:
            self.new_added_prefixes.remove(self.current_prefix)
            self.new_added_prefixes.add(new_name)

        self.current_prefix = new_name
        self.refresh_prefix_list()

    def delete_prefix(self):
        if not self.current_prefix:
            return

        ok = False
        if confirm_dialog is not None:
            ok = bool(confirm_dialog(self, "确认删除", f"确定删除分类「{self.current_prefix}」及其全部词条吗？"))
        else:
            ok = QMessageBox.question(self, "确认删除", f"确定删除分类「{self.current_prefix}」及其全部词条吗？") == QMessageBox.Yes

        if not ok:
            return

        self.data.pop(self.current_prefix, None)
        self.new_added_prefixes.discard(self.current_prefix)
        self.current_prefix = None
        self.refresh_prefix_list()

        # 删除属于“结构性变更”，建议直接落盘
        save_zhuli_keywords(self.data)
        self.sig_realtime_changed.emit(self.data)

    # ===================== 右侧词条操作 =====================
    def _active_key(self) -> Tuple[str, QListWidget, str]:
        idx = self.tabs.currentIndex()
        if idx == 0:
            return "must", self.must_list, "必含词"
        if idx == 1:
            return "any", self.any_list, "意图词"
        return "deny", self.deny_list, "排除词"

    def _render_prefix(self, prefix: str):
        cfg = self.data.get(prefix) or {"priority": 0, "must": [], "any": [], "deny": [], "prefix": prefix}

        must = _dedup_keep_order(list(map(str, cfg.get("must", []) or [])))
        any_ = _dedup_keep_order(list(map(str, cfg.get("any", []) or [])))
        deny = _dedup_keep_order(list(map(str, cfg.get("deny", []) or [])))

        cfg["must"] = must
        cfg["any"] = any_
        cfg["deny"] = deny
        cfg.setdefault("priority", 0)
        cfg.setdefault("prefix", prefix)
        self.data[prefix] = cfg

        # priority
        self.sp_priority.blockSignals(True)
        self.sp_priority.setValue(int(cfg.get("priority", 0) or 0))
        self.sp_priority.blockSignals(False)

        # lists
        self.must_list.clear()
        self.any_list.clear()
        self.deny_list.clear()

        for w in must:
            self.must_list.addItem(QListWidgetItem(w))
        for w in any_:
            self.any_list.addItem(QListWidgetItem(w))
        for w in deny:
            self.deny_list.addItem(QListWidgetItem(w))

        self._update_tab_counts(prefix)

    def _update_tab_counts(self, prefix: str):
        cfg = self.data.get(prefix) or {}
        self.tabs.setTabText(0, f"必含词（{len(cfg.get('must', []) or [])}）")
        self.tabs.setTabText(1, f"意图词（{len(cfg.get('any', []) or [])}）")
        self.tabs.setTabText(2, f"排除词（{len(cfg.get('deny', []) or [])}）")

    def _update_tab_counts_empty(self):
        self.tabs.setTabText(0, "必含词（0）")
        self.tabs.setTabText(1, "意图词（0）")
        self.tabs.setTabText(2, "排除词（0）")

    def batch_add_words(self):
        if not self.current_prefix:
            return

        key, _, cname = self._active_key()

        text = None
        if MultiLineInputDialog is not None:
            dlg = MultiLineInputDialog(self, f"批量添加{cname}", "支持：换行分隔 / 逗号分隔（一次可粘贴很多）", default="")
            dlg.exec()
            if not getattr(dlg, "ok", False):
                return
            text = getattr(dlg, "text", "")
        else:
            text, ok = QInputDialog.getMultiLineText(self, f"批量添加{cname}", "每行一个（或逗号分隔）：")
            if not ok:
                return

        words = _split_words(text)
        if not words:
            return

        cfg = self.data.get(self.current_prefix) or {"priority": 0, "must": [], "any": [], "deny": [], "prefix": self.current_prefix}
        arr = list(map(str, cfg.get(key, []) or []))
        arr.extend(words)
        cfg[key] = _dedup_keep_order(arr)
        self.data[self.current_prefix] = cfg

        self._render_prefix(self.current_prefix)
        self.sig_realtime_changed.emit(self.data)

    def delete_selected_words(self):
        if not self.current_prefix:
            return

        key, lst, cname = self._active_key()
        items = lst.selectedItems()
        if not items:
            return

        ok = False
        if confirm_dialog is not None:
            ok = bool(confirm_dialog(self, "确认删除", f"确定删除选中的 {len(items)} 个{cname}吗？"))
        else:
            ok = QMessageBox.question(self, "确认删除", f"确定删除选中的 {len(items)} 个{cname}吗？") == QMessageBox.Yes

        if not ok:
            return

        selected = set(i.text() for i in items)
        cfg = self.data[self.current_prefix]
        cfg[key] = [w for w in (cfg.get(key, []) or []) if str(w) not in selected]
        self.data[self.current_prefix] = cfg

        self._render_prefix(self.current_prefix)
        self.sig_realtime_changed.emit(self.data)

    def clear_current_tab(self):
        if not self.current_prefix:
            return

        key, _, cname = self._active_key()
        ok = False
        if confirm_dialog is not None:
            ok = bool(confirm_dialog(self, "确认清空", f"确定清空当前分类的「{cname}」吗？"))
        else:
            ok = QMessageBox.question(self, "确认清空", f"确定清空当前分类的「{cname}」吗？") == QMessageBox.Yes

        if not ok:
            return

        self.data[self.current_prefix][key] = []
        self._render_prefix(self.current_prefix)
        self.sig_realtime_changed.emit(self.data)

    def clear_current_prefix(self):
        if not self.current_prefix:
            return

        ok = False
        if confirm_dialog is not None:
            ok = bool(confirm_dialog(self, "确认清空", f"确定清空分类「{self.current_prefix}」下所有词条吗？"))
        else:
            ok = QMessageBox.question(self, "确认清空", f"确定清空分类「{self.current_prefix}」下所有词条吗？") == QMessageBox.Yes

        if not ok:
            return

        cfg = self.data[self.current_prefix]
        cfg["must"] = []
        cfg["any"] = []
        cfg["deny"] = []
        self.data[self.current_prefix] = cfg
        self._render_prefix(self.current_prefix)
        self.sig_realtime_changed.emit(self.data)

    # ===================== 导入 / 导出 / 保存 =====================
    def export_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出助播关键词", "zhuli_keywords.json", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def import_merge_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入助播关键词（合并）", "", "JSON (*.json)")
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                incoming = json.load(f)
            if not isinstance(incoming, dict):
                raise ValueError("导入文件必须是 dict")
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))
            return

        ok = False
        if confirm_dialog is not None:
            ok = bool(confirm_dialog(self, "确认导入", "将按“合并”方式导入：同名分类会覆盖/补齐字段。\n确定继续？"))
        else:
            ok = QMessageBox.question(self, "确认导入", "将按“合并”方式导入：同名分类会覆盖/补齐字段。\n确定继续？") == QMessageBox.Yes
        if not ok:
            return

        self.data = merge_zhuli_keywords(self.data, incoming)
        self.refresh_prefix_list()
        self.sig_realtime_changed.emit(self.data)

    def save_all(self):
        save_zhuli_keywords(self.data)
        QMessageBox.information(self, "保存成功", "助播关键词已保存")

    # ===================== 实时更新（不保存） =====================
    def _realtime_update_priority(self, val: int):
        if not self.current_prefix:
            return
        cfg = self.data.get(self.current_prefix) or {"priority": 0, "must": [], "any": [], "deny": [], "prefix": self.current_prefix}
        cfg["priority"] = int(val)
        self.data[self.current_prefix] = cfg
        self.sig_realtime_changed.emit(self.data)

    # ===================== 检查目录（按 config.ZHULI_AUDIO_DIR） =====================
    def scan_zhuli_audio_dir(self):
        zhuli_dir = _get_zhuli_audio_dir()
        zhuli_dir.mkdir(parents=True, exist_ok=True)

        exts = _get_supported_exts()
        files = [p for p in zhuli_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]

        if not files:
            QMessageBox.information(self, "检查目录", f"目录为空或没有音频：\n{zhuli_dir}")
            return

        prefixes: List[str] = []
        for p in files:
            pref = _guess_prefix_from_filename(p.name)
            if pref:
                prefixes.append(pref)

        prefixes = _dedup_keep_order(prefixes)
        new_prefixes = [p for p in prefixes if p not in self.data]

        if not new_prefixes:
            QMessageBox.information(self, "检查目录", "未发现需要新增的分类（都已存在）。")
            return

        preview = "、".join(new_prefixes[:12])
        more = "" if len(new_prefixes) <= 12 else f" …（共 {len(new_prefixes)} 个）"
        msg = f"检测到 {len(new_prefixes)} 个新分类：\n{preview}{more}\n\n是否添加为分类并保存？"

        ok = False
        if confirm_dialog is not None:
            ok = bool(confirm_dialog(self, "检查目录", msg))
        else:
            ok = QMessageBox.question(self, "检查目录", msg) == QMessageBox.Yes

        if not ok:
            return

        for name in new_prefixes:
            self.data[name] = {"priority": 0, "must": [], "any": [], "deny": [], "prefix": name}
            self.new_added_prefixes.add(name)

        # ✅按你要求：这里是“提示是否保存为分类”——确认后直接落盘
        save_zhuli_keywords(self.data)
        self.refresh_prefix_list()
        self.sig_realtime_changed.emit(self.data)

        # 选中第一个新增
        first = new_prefixes[0]
        for i in range(self.prefix_list.count()):
            if self.prefix_list.item(i).data(Qt.UserRole) == first:
                self.prefix_list.setCurrentRow(i)
                break
