# ui/pages/page_keywords.py
import os
import re
import time
import importlib.util
from typing import Tuple, List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QTabWidget, QPushButton,
    QFileDialog, QAbstractItemView
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut

from ui.dialogs import confirm_dialog, TextInputDialog, MultiLineInputDialog
from core.keyword_io import (
    load_keywords, save_keywords, reload_keywords_hot,
    export_keywords_json, load_keywords_json, merge_keywords
)
from core.audio_tools import scan_audio_prefixes
from config import KEYWORDS_BASE_DIR, SUPPORTED_AUDIO_EXTS, KEYWORD_RULE_URL


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


def _guess_keywords_py_path() -> str:
    """
    尝试找到 keywords.py 的真实路径（多路径兜底）
    """
    cands: List[str] = []

    # 1) config.KEYWORDS_PY_PATH（如果你有）
    try:
        from config import KEYWORDS_PY_PATH  # type: ignore
        if KEYWORDS_PY_PATH:
            cands.append(str(KEYWORDS_PY_PATH))
    except Exception:
        pass

    # 2) 当前工作目录
    cands.append(os.path.join(os.getcwd(), "keywords.py"))

    # 3) 从本文件位置向上推断
    here = os.path.abspath(os.path.dirname(__file__))
    cands.append(os.path.abspath(os.path.join(here, ".", ".", "keywords.py")))
    cands.append(os.path.abspath(os.path.join(here, ".", ".", ".", "keywords.py")))
    cands.append(os.path.abspath(os.path.join(here, ".", ".", ".", ".", "keywords.py")))

    for p in cands:
        if p and os.path.exists(p) and os.path.isfile(p):
            return p
    return ""


def _load_keywords_fresh_from_file() -> Dict[str, Any]:
    """
    ✅ 强制从磁盘执行 keywords.py，完全绕过 import 缓存
    （你删一行也会立即生效）
    """
    kw_path = _guess_keywords_py_path()
    if not kw_path:
        return {}

    mod_name = f"_keywords_hot_{int(time.time() * 1000)}"
    spec = importlib.util.spec_from_file_location(mod_name, kw_path)
    if not spec or not spec.loader:
        return {}

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 直接执行 keywords.py

    # 兼容不同变量名（按你项目最常见优先）
    for name in ("ZHULI_KEYWORDS", "KEYWORDS", "KEYWORD_RULES", "KEYWORD_MAP"):
        val = getattr(mod, name, None)
        if isinstance(val, dict):
            return val

    # 兜底：抓到第一个 dict
    for k in dir(mod):
        if k.startswith("__"):
            continue
        val = getattr(mod, k, None)
        if isinstance(val, dict):
            return val

    return {}


class KeywordPanel(QWidget):
    """
    商用版关键词管理（嵌入主界面）
    - 全中文：必含词 / 意图词 / 排除词 / 回复词
    - 导入合并 JSON / 导出 JSON
    - 保存并热更新 keywords.py
    - ✅ 新增：进入页面时强制从磁盘刷新（refresh_from_disk）
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 初始读一次（后续切换页面会 refresh_from_disk）
        self.data: Dict[str, Any] = load_keywords() or {}
        self.current_prefix: Optional[str] = None
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
        self.btn_check_audio = QPushButton("检查音频")
        self.btn_open_audio_dir = QPushButton("打开音频目录")
        self.btn_save = QPushButton("保存并热更新")

        # 让“保存并热更新”更明显（不依赖 QSS）
        self.btn_save.setFixedHeight(38)
        self.btn_save.setStyleSheet("""
        QPushButton{
            background:#21B36B;
            color:white;
            font-weight:900;
            border:none;
            border-radius:10px;
            padding:6px 16px;
        }
        QPushButton:hover{ background:#1EA460; }
        QPushButton:pressed{ background:#17884F; }
        """)

        for b in (self.btn_export, self.btn_import, self.btn_check_audio, self.btn_open_audio_dir):
            b.setFixedHeight(36)

        header.addWidget(self.btn_export)
        header.addWidget(self.btn_import)
        header.addWidget(self.btn_check_audio)
        header.addWidget(self.btn_open_audio_dir)
        header.addSpacing(8)
        header.addWidget(self.btn_save)

        root.addLayout(header)

        # ===== 搜索 + 分类操作 =====
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索分类（支持模糊）")
        self.btn_add_prefix = QPushButton("新建分类")
        self.btn_rename_prefix = QPushButton("重命名")
        self.btn_delete_prefix = QPushButton("删除分类")
        self.btn_delete_all = QPushButton("删除全部")

        for b in (self.btn_add_prefix, self.btn_rename_prefix, self.btn_delete_prefix, self.btn_delete_all):
            b.setFixedHeight(36)

        bar.addWidget(self.search, 1)
        bar.addWidget(self.btn_add_prefix)
        bar.addWidget(self.btn_rename_prefix)
        bar.addWidget(self.btn_delete_prefix)
        bar.addWidget(self.btn_delete_all)
        root.addLayout(bar)

        # ===== 主体：左列表 + 右编辑 =====
        body = QHBoxLayout()
        body.setSpacing(10)

        self.prefix_list = QListWidget()
        self.prefix_list.setFixedWidth(240)
        self.prefix_list.setSelectionMode(QAbstractItemView.SingleSelection)

        body.addWidget(self.prefix_list)

        right = QVBoxLayout()
        self.lbl_current = QLabel("当前分类：-")
        self.lbl_current.setStyleSheet("font-weight:800;")
        right.addWidget(self.lbl_current)

        self.tabs = QTabWidget()
        self.must_list = QListWidget()
        self.any_list = QListWidget()
        self.deny_list = QListWidget()
        self.reply_list = QListWidget()

        for lst in (self.must_list, self.any_list, self.deny_list, self.reply_list):
            lst.setSelectionMode(QAbstractItemView.ExtendedSelection)

        self.tabs.addTab(self.must_list, "必含词（0）")
        self.tabs.addTab(self.any_list, "意图词（0）")
        self.tabs.addTab(self.deny_list, "排除词（0）")
        self.tabs.addTab(self.reply_list, "回复词（0）")

        right.addWidget(self.tabs, 1)

        # ===== 右侧按钮 =====
        op = QHBoxLayout()
        self.btn_batch_add = QPushButton("批量添加")
        self.btn_delete_selected = QPushButton("删除选中")
        self.btn_clear_tab = QPushButton("清空当前标签")
        self.btn_open_rule = QPushButton("规则说明")

        for b in (self.btn_batch_add, self.btn_delete_selected, self.btn_clear_tab, self.btn_open_rule):
            b.setFixedHeight(36)

        op.addWidget(self.btn_batch_add)
        op.addWidget(self.btn_delete_selected)
        op.addWidget(self.btn_clear_tab)
        op.addStretch(1)
        op.addWidget(self.btn_open_rule)
        right.addLayout(op)

        body.addLayout(right, 1)
        root.addLayout(body, 1)

        # ===== 绑定信号 =====
        self.search.textChanged.connect(self.refresh_prefix_list)
        self.prefix_list.itemSelectionChanged.connect(self.on_select_prefix)

        self.btn_add_prefix.clicked.connect(self.add_prefix)
        self.btn_rename_prefix.clicked.connect(self.rename_prefix)
        self.btn_delete_prefix.clicked.connect(self.delete_prefix)
        self.btn_delete_all.clicked.connect(self.delete_all_keywords)

        self.btn_batch_add.clicked.connect(self.batch_add_words)
        self.btn_delete_selected.clicked.connect(self.delete_selected_words)
        self.btn_clear_tab.clicked.connect(self.clear_current_tab)
        self.btn_open_rule.clicked.connect(self.open_rule_help)

        self.btn_export.clicked.connect(self.export_json)
        self.btn_import.clicked.connect(self.import_merge_json)
        self.btn_save.clicked.connect(self.save_and_hot_reload)
        self.btn_check_audio.clicked.connect(self.check_audio_prefixes)
        self.btn_open_audio_dir.clicked.connect(self.open_audio_dir)

        # 快捷键：Ctrl+S 保存
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_and_hot_reload)

        # 初始填充
        self.refresh_prefix_list()

    # ===================== 页面显示刷新（核心） =====================
    def on_show(self):
        """MainWindow 切到该页面时调用"""
        self.refresh_from_disk()

    def refresh_from_disk(self):
        """
        ✅ 强制从磁盘重新读取 keywords.py（删除/修改立刻生效）
        """
        try:
            incoming = _load_keywords_fresh_from_file()
            if isinstance(incoming, dict):
                self.data = incoming
            else:
                self.data = {}
        except Exception:
            # 兜底：至少用你原来的 load_keywords
            self.data = load_keywords() or {}

        keep = self.current_prefix if (self.current_prefix and self.current_prefix in self.data) else None
        self.current_prefix = keep
        self.refresh_prefix_list()

    # ===================== 功能按钮 =====================
    def open_rule_help(self):
        try:
            QDesktopServices.openUrl(QUrl(str(KEYWORD_RULE_URL)))
        except Exception:
            pass

    def open_audio_dir(self):
        try:
            base = str(KEYWORDS_BASE_DIR)
            if base and os.path.exists(base):
                QDesktopServices.openUrl(QUrl.fromLocalFile(base))
        except Exception:
            pass

    def check_audio_prefixes(self):
        try:
            keyword_prefixes = set(self.data.keys())
            audio_prefixes = set(scan_audio_prefixes(KEYWORDS_BASE_DIR, SUPPORTED_AUDIO_EXTS) or [])

            reserved_prefixes = {"讲解", "关注", "点赞", "下单"}
            audio_prefixes = {p for p in audio_prefixes if p not in reserved_prefixes}

            no_audio = sorted(keyword_prefixes - audio_prefixes)
            no_keyword = sorted(audio_prefixes - keyword_prefixes)

            # ✅ 自动导入新发现的音频前缀
            imported_count = 0
            if no_keyword:
                for prefix in no_keyword:
                    if prefix not in self.data:
                        # 创建新的关键词分类
                        self.data[prefix] = {
                            "priority": 0,
                            "must": [],
                            "any": [],
                            "deny": [],
                            "reply": [],
                            "prefix": prefix
                        }
                        self.new_added_prefixes.add(prefix)
                        imported_count += 1

            msg = []
            if no_audio:
                msg.append("❌ 以下分类缺少对应音频：\n" + "、".join(no_audio))
            
            if imported_count > 0:
                msg.append(f"✅ 自动导入 {imported_count} 个新关键词分类：\n" + "、".join(no_keyword))
            elif no_keyword:
                msg.append("检测到新音频前缀（关键词未配置）：\n" + "、".join(no_keyword))
            
            if not msg:
                msg.append("✅ 关键词与音频前缀完全匹配，无需修复。")

            # 显示检查结果
            confirm_dialog(self, "自动导入检查", "\n\n".join(msg))
            
            # 如果有新导入的分类，刷新UI并保存
            if imported_count > 0:
                self.refresh_prefix_list()
                # 自动保存
                self.save_and_hot_reload()
                
        except Exception as e:
            confirm_dialog(self, "检查失败", str(e))

    # ===================== 分类列表渲染 =====================
    def refresh_prefix_list(self):
        """
        根据搜索条件刷新分类列表，并保持当前选中（如果还能找到）。
        """
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
            item.setData(Qt.UserRole, p)  # 真正的 prefix
            self.prefix_list.addItem(item)

        self.prefix_list.blockSignals(False)

        # ✅ 修复：保持选中要用 UserRole，不要用 text（text 可能带“（新）”）
        if keep:
            for i in range(self.prefix_list.count()):
                it = self.prefix_list.item(i)
                if it and it.data(Qt.UserRole) == keep:
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
            self.reply_list.clear()
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
        if not name or name in self.data:
            return

        self.data[name] = {"priority": 0, "must": [], "any": [], "deny": [], "reply": [], "prefix": name}
        self.new_added_prefixes.add(name)
        self.refresh_prefix_list()

        for i in range(self.prefix_list.count()):
            it = self.prefix_list.item(i)
            if it and it.data(Qt.UserRole) == name:
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
        if not new_name or new_name == self.current_prefix or new_name in self.data:
            return

        cfg = self.data.pop(self.current_prefix)
        cfg["prefix"] = new_name
        self.data[new_name] = cfg
        self.current_prefix = new_name

        # 新标记迁移
        if self.current_prefix in self.new_added_prefixes:
            self.new_added_prefixes.discard(self.current_prefix)
            self.new_added_prefixes.add(new_name)

        self.refresh_prefix_list()

    def delete_prefix(self):
        if not self.current_prefix:
            return
        if not confirm_dialog(self, "确认删除", f"确定删除分类「{self.current_prefix}」及其全部词条吗？"):
            return
        self.data.pop(self.current_prefix, None)
        self.new_added_prefixes.discard(self.current_prefix)
        self.current_prefix = None
        self.refresh_prefix_list()

    # ===================== 词条编辑 =====================
    def _active_key(self) -> Tuple[str, QListWidget, str]:
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
        must = _dedup_keep_order(list(map(str, cfg.get("must", []) or [])))
        any_ = _dedup_keep_order(list(map(str, cfg.get("any", []) or [])))
        deny = _dedup_keep_order(list(map(str, cfg.get("deny", []) or [])))
        reply = _dedup_keep_order(list(map(str, cfg.get("reply", []) or [])))

        cfg["must"] = must
        cfg["any"] = any_
        cfg["deny"] = deny
        cfg["reply"] = reply
        cfg["prefix"] = prefix
        if "priority" not in cfg:
            cfg["priority"] = 0
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
        dlg = MultiLineInputDialog(self, f"批量添加{cname}", "支持：换行分隔 / 逗号分隔（一次可粘贴很多）", default="")
        dlg.exec()
        if not dlg.ok:
            return

        words = _split_words(dlg.text)
        if not words:
            return

        cfg = self.data.get(self.current_prefix) or {"priority": 0, "must": [], "any": [], "deny": [], "reply": [], "prefix": self.current_prefix}
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

    def delete_all_keywords(self):
        if not confirm_dialog(self, "危险操作", "确定删除全部关键词分类吗？此操作不可恢复（除非你有备份）。"):
            return
        self.data = {}
        self.current_prefix = None
        self.new_added_prefixes.clear()
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

        # 你原来用 reload_keywords_hot 的逻辑保留，但“刷新UI来源”改为磁盘强制执行
        try:
            _ = reload_keywords_hot()
        except Exception:
            pass

        self.refresh_from_disk()
        self.new_added_prefixes.clear()


class KeywordPage(QWidget):
    """
    MainWindow 里注册的页面（MainWindow 切换时会调用 on_show）
    """
    def __init__(self, ctx: dict):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.panel = KeywordPanel(self)   # ✅必须叫 panel
        lay.addWidget(self.panel, 1)

    def on_show(self):
        # ✅ 点击【关键词设置】菜单就刷新 keywords.py
        self.panel.on_show()

    def showEvent(self, event):
        super().showEvent(event)
        # ✅页面显示也刷新（双保险）
        self.panel.on_show()
