import os
import re
from typing import Tuple, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QTabWidget, QPushButton,
    QFileDialog, QAbstractItemView, QTextBrowser, QDialog
)

from ui.dialogs import confirm_dialog, TextInputDialog, MultiLineInputDialog
from core.keyword_io import (
    load_keywords, save_keywords, reload_keywords_hot,
    export_keywords_json, load_keywords_json, merge_keywords
)

from PySide6.QtCore import QUrl

def _split_words(raw: str) -> List[str]:
    """支持：换行 / 英文逗号 / 中文逗号 / 分号"""
    parts = re.split(r"[\n,，;；]+", raw or "")
    return [p.strip() for p in parts if p.strip()]


def _dedup_keep_order(words: List[str]) -> List[str]:
    seen = set()
    out = []
    for w in words:
        w = str(w).strip()
        if not w:
            continue
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


class KeywordPanel(QWidget):
    """
    商用版关键词管理（嵌入主界面）
    - 全中文：必含词 / 意图词 / 排除词
    - Tab 角标实时显示数量
    - Tab 右上角紧挨标签的问号按钮（setCornerWidget），加载 ui/rule_help.html
    - 导入合并 JSON / 导出 JSON
    - 保存并热更新 keywords.py
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.data = load_keywords()  # {prefix: {priority, must, any, deny, prefix}}
        self.current_prefix: str | None = None

        self.new_added_prefixes = set()


        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ===== 顶部栏 =====
        header = QHBoxLayout()



        title = QLabel("关键词管理")
        title.setStyleSheet("font-size: 16px; font-weight: 800;")
        header.addWidget(title)
        header.addStretch(1)

        self.btn_export = QPushButton("导出")
        self.btn_import = QPushButton("导入（合并）")
        self.btn_save = QPushButton("保存并热更新")

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

        # ===== 右侧：词库 =====
        right  = QVBoxLayout()
        body.addLayout(right, 5)

        # 当前分类行（标签 + 问号按钮）
        current_row = QHBoxLayout()

        self.lbl_current = QLabel("当前分类：-")
        self.lbl_current.setStyleSheet("font-size: 14px; font-weight: 700;")
        current_row.addWidget(self.lbl_current)

        # 问号按钮
        self.btn_help = QPushButton()
        self.btn_help.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "..", "img", "help.svg")))

        self.btn_help.setToolTip("查看关键词规则说明")
        self.btn_help.setFixedSize(22, 22)
        self.btn_help.setStyleSheet("margin-left:6px;")  # 与文字留点间距
        self.btn_help.clicked.connect(self.show_rule_help)
        self.btn_help.setStyleSheet("""
        QPushButton {
            border: none;
            background: transparent;
        }
        QPushButton:hover {
            background: rgba(0, 123, 255, 1);
            border-radius: 11px;
        }
        """)



        current_row.addWidget(self.btn_help)
        current_row.addStretch(1)  # 把右边顶开，保持左对齐

        right.addLayout(current_row)

        # Tab
        self.tabs = QTabWidget()
        right.addWidget(self.tabs, 1)

        self.must_list = QListWidget()
        self.any_list = QListWidget()
        self.deny_list = QListWidget()
        # ✅新增：回复词（命中关键词后自动回复客户）
        self.reply_list = QListWidget()

        for lst in (self.must_list, self.any_list, self.deny_list, self.reply_list):
            lst.setSelectionMode(QAbstractItemView.ExtendedSelection)

        self.tabs.addTab(self.must_list, "必含词（0）")
        self.tabs.addTab(self.any_list, "意图词（0）")
        self.tabs.addTab(self.deny_list, "排除词（0）")
        self.tabs.addTab(self.reply_list, "回复词（0）")


        # 操作区
        ops = QHBoxLayout()
        self.btn_batch_add = QPushButton("批量添加")
        self.btn_del_selected = QPushButton("删除选中")
        self.btn_clear_tab = QPushButton("清空当前页")
        self.btn_clear_prefix = QPushButton("清空本分类")
        self.btn_delete_all = QPushButton("删除全部关键词")



        for b in (self.btn_batch_add, self.btn_del_selected, self.btn_clear_tab, self.btn_clear_prefix, self.btn_delete_all):
            b.setFixedHeight(34)

        ops.addWidget(self.btn_batch_add)
        ops.addWidget(self.btn_del_selected)
        ops.addWidget(self.btn_clear_tab)
        ops.addWidget(self.btn_clear_prefix)
        ops.addStretch(1)
        ops.addWidget(self.btn_delete_all)
        right.addLayout(ops)

        # ===== 绑定 =====
        self.btn_add_prefix.clicked.connect(self.add_prefix)
        self.btn_rename_prefix.clicked.connect(self.rename_prefix)
        self.btn_del_prefix.clicked.connect(self.delete_prefix)

        self.btn_batch_add.clicked.connect(self.batch_add_words)
        self.btn_del_selected.clicked.connect(self.delete_selected_words)
        self.btn_clear_tab.clicked.connect(self.clear_current_tab)
        self.btn_clear_prefix.clicked.connect(self.clear_current_prefix)
        self.btn_delete_all.clicked.connect(self.delete_all_keywords)

        self.btn_export.clicked.connect(self.export_json)
        self.btn_import.clicked.connect(self.import_merge_json)
        self.btn_save.clicked.connect(self.save_and_hot_reload)

        # 初始加载
        self.refresh_prefix_list()

    # ===================== 规则说明（HTML） =====================
    def show_rule_help(self):
        html_path = os.path.join(os.path.dirname(__file__), "rule_help.html")

        dlg = QDialog(self)
        dlg.setWindowTitle("关键词规则说明")
        dlg.resize(760, 560)
        layout = QVBoxLayout(dlg)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet("background:#0F1A2E; color:#E6EEF8; border-radius:10px; padding:8px;")

        if os.path.exists(html_path):
            with open(html_path, "r", encoding="utf-8") as f:
                html = f.read()
            base_dir = os.path.dirname(html_path)
            browser.setHtml(html)
            browser.document().setBaseUrl(QUrl.fromLocalFile(base_dir + os.sep))
        else:
            browser.setHtml("<h3 style='color:#FF6B6B'>未找到 ui/rule_help.html</h3>")

        layout.addWidget(browser)

        btn_close = QPushButton("关闭")
        btn_close.setFixedHeight(36)
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close)

        dlg.exec()

    # ===================== 左侧分类 =====================
    def refresh_prefix_list(self):
        """
        根据搜索条件刷新分类列表，并保持当前选中（如果还能找到）。
        """
        keyword = (self.search.text() or "").strip()
        keep = self.current_prefix

        self.prefix_list.blockSignals(True)
        self.prefix_list.clear()

        all_prefixes = list(self.data.keys())

        # 老的在前，新加的在后
        normal = [p for p in all_prefixes if p not in self.new_added_prefixes]
        new = [p for p in all_prefixes if p in self.new_added_prefixes]

        prefixes = sorted(normal) + sorted(new)


        for p in prefixes:
            if keyword and keyword not in p:
                continue
            show_name = p + "（新）" if p in self.new_added_prefixes else p
            item = QListWidgetItem(show_name)
            item.setData(Qt.UserRole, p)  # 真正的 prefix
            self.prefix_list.addItem(item)

        self.prefix_list.blockSignals(False)

        # 尽量保持原选中
        if keep:
            for i in range(self.prefix_list.count()):
                if self.prefix_list.item(i).text() == keep:
                    self.prefix_list.setCurrentRow(i)
                    return

        # 否则选第一个
        if self.prefix_list.count() > 0:
            self.prefix_list.setCurrentRow(0)
        else:
            # 没有分类
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
        dlg = TextInputDialog(self, "新建分类", "请输入分类名（例如：炉膛 / 尺寸 / 售后）：")
        dlg.exec()
        if not dlg.ok or not dlg.value:
            return

        name = dlg.value.strip()
        if not name:
            return
        if name in self.data:
            return

        self.data[name] = {"priority": 0, "must": [], "any": [], "deny": [], "prefix": name}
        self.refresh_prefix_list()

        # 选中它
        for i in range(self.prefix_list.count()):
            if self.prefix_list.item(i).text() == name:
                self.prefix_list.setCurrentRow(i)
                break

    def rename_prefix(self):
        if not self.current_prefix:
            return

        dlg = TextInputDialog(self, "重命名分类", "请输入新分类名：", default=self.current_prefix)
        dlg.exec()
        if not dlg.ok or not dlg.value:
            return

        new_name = dlg.value.strip()
        if not new_name or new_name == self.current_prefix:
            return
        if new_name in self.data:
            return

        cfg = self.data.pop(self.current_prefix)
        cfg["prefix"] = new_name
        self.data[new_name] = cfg
        self.current_prefix = new_name
        self.refresh_prefix_list()

    def delete_prefix(self):
        if not self.current_prefix:
            return

        if not confirm_dialog(self, "确认删除", f"确定删除分类「{self.current_prefix}」及其全部词条吗？"):
            return

        self.data.pop(self.current_prefix, None)
        self.current_prefix = None
        self.refresh_prefix_list()

    # ===================== 右侧词条操作 =====================
    def _active_key(self) -> Tuple[str, QListWidget, str]:
        """
        返回：(key, listWidget, 中文名)
        key ∈ {"must","any","deny","reply"}
        """
        idx = self.tabs.currentIndex()
        if idx == 0:
            return "must", self.must_list, "必含词"
        if idx == 1:
            return "any", self.any_list, "意图词"
        if idx == 2:
            return "deny", self.deny_list, "排除词"
        return "reply", self.reply_list, "回复词"

    def _render_prefix(self, prefix: str):
        cfg = self.data.get(prefix) or {}
        must = cfg.get("must", []) or []
        any_ = cfg.get("any", []) or []
        deny = cfg.get("deny", []) or []
        reply = cfg.get("reply", []) or []

        # 统一去重（防止导入/粘贴重复）
        must = _dedup_keep_order(list(map(str, must)))
        any_ = _dedup_keep_order(list(map(str, any_)))
        deny = _dedup_keep_order(list(map(str, deny)))
        reply = _dedup_keep_order(list(map(str, reply)))

        cfg["must"] = must
        cfg["any"] = any_
        cfg["deny"] = deny
        cfg["reply"] = reply
        self.data[prefix] = cfg

        self.must_list.clear()
        self.any_list.clear()
        self.deny_list.clear()
        self.reply_list.clear()

        for w in must:
            self.must_list.addItem(QListWidgetItem(w))
        for w in any_:
            self.any_list.addItem(QListWidgetItem(w))
        for w in deny:
            self.deny_list.addItem(QListWidgetItem(w))
        for w in reply:
            self.reply_list.addItem(QListWidgetItem(w))

        self._update_tab_counts(prefix)

    def _update_tab_counts(self, prefix: str):
        cfg = self.data.get(prefix) or {}
        self.tabs.setTabText(0, f"必含词（{len(cfg.get('must', []) or [])}）")
        self.tabs.setTabText(1, f"意图词（{len(cfg.get('any', []) or [])}）")
        self.tabs.setTabText(2, f"排除词（{len(cfg.get('deny', []) or [])}）")
        self.tabs.setTabText(3, f"回复词（{len(cfg.get('reply', []) or [])}）")

    def _update_tab_counts_empty(self):
        self.tabs.setTabText(0, "必含词（0）")
        self.tabs.setTabText(1, "意图词（0）")
        self.tabs.setTabText(2, "排除词（0）")
        self.tabs.setTabText(3, "回复词（0）")

    def batch_add_words(self):
        if not self.current_prefix:
            return

        key, _, cname = self._active_key()
        title = f"批量添加{cname}"
        tip = "支持：换行分隔 / 逗号分隔（一次可粘贴很多）"
        dlg = MultiLineInputDialog(self, title, tip, default="")
        dlg.exec()
        if not dlg.ok:
            return

        words = _split_words(dlg.text)
        if not words:
            return

        cfg = self.data.get(self.current_prefix) or {"priority": 0, "must": [], "any": [], "deny": [], "prefix": self.current_prefix}
        arr = list(map(str, cfg.get(key, []) or []))
        arr.extend(words)
        cfg[key] = _dedup_keep_order(arr)
        self.data[self.current_prefix] = cfg

        self._render_prefix(self.current_prefix)

    def delete_selected_words(self):
        if not self.current_prefix:
            return

        key, lst, cname = self._active_key()
        items = lst.selectedItems()
        if not items:
            return

        if not confirm_dialog(self, "确认删除", f"确定删除选中的 {len(items)} 个{cname}吗？"):
            return

        selected = set(i.text() for i in items)
        cfg = self.data[self.current_prefix]
        cfg[key] = [w for w in (cfg.get(key, []) or []) if str(w) not in selected]
        self.data[self.current_prefix] = cfg

        self._render_prefix(self.current_prefix)

    def clear_current_tab(self):
        if not self.current_prefix:
            return

        key, _, cname = self._active_key()
        if not confirm_dialog(self, "确认清空", f"确定清空当前分类的「{cname}」吗？"):
            return

        self.data[self.current_prefix][key] = []
        self._render_prefix(self.current_prefix)

    def clear_current_prefix(self):
        if not self.current_prefix:
            return

        if not confirm_dialog(self, "确认清空", f"确定清空分类「{self.current_prefix}」下所有词条吗？"):
            return

        cfg = self.data[self.current_prefix]
        cfg["must"] = []
        cfg["any"] = []
        cfg["deny"] = []
        cfg["reply"] = []
        self.data[self.current_prefix] = cfg
        self._render_prefix(self.current_prefix)

    def delete_all_keywords(self):
        if not confirm_dialog(self, "危险操作", "确定删除全部关键词分类吗？此操作不可恢复（除非你有备份）。"):
            return

        self.data = {}
        self.current_prefix = None
        self.refresh_prefix_list()

    # ===================== 导入 / 导出 / 保存 =====================
    def export_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出关键词", "keywords.json", "JSON (*.json)")
        if not path:
            return
        export_keywords_json(self.data, path)

    def import_merge_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入关键词（合并）", "", "JSON (*.json)")
        if not path:
            return

        incoming = load_keywords_json(path)
        if not incoming:
            return

        if not confirm_dialog(self, "确认导入", "将按“合并”方式导入：同名分类会去重追加词条。\n确定继续？"):
            return

        self.data = merge_keywords(self.data, incoming)
        self.refresh_prefix_list()

    def save_and_hot_reload(self):
        # 保存到 keywords.py
        save_keywords(self.data)
        # 热加载更新 runtime
        self.data = reload_keywords_hot()
        # 刷新 UI
        self.refresh_prefix_list()
        self.new_added_prefixes.clear()