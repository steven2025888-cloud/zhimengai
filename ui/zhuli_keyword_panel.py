from __future__ import annotations

import json
import os
import sys
import re
from pathlib import Path
from typing import Dict, List, Tuple

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QTabWidget, QPushButton,
    QFileDialog, QAbstractItemView, QMessageBox, QSpinBox, QInputDialog,
    QComboBox,  # ✅ 新增
)

from core.zhuli_keyword_io import load_zhuli_keywords, save_zhuli_keywords, merge_zhuli_keywords

from core.state import app_state  # ✅ 新增


# ===== runtime_state.json 统一路径（避免工作目录变化导致不保存） =====
def _project_root() -> Path:
    # ui/*.py -> parents[1] is project root
    return Path(__file__).resolve().parents[1]


def _runtime_state_path() -> Path:
    return _project_root() / "runtime_state.json"


def load_runtime_state() -> dict:
    p = _runtime_state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_runtime_state(state: dict):
    p = _runtime_state_path()
    try:
        p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # 最差也不要让 UI 崩
        pass


def _open_in_file_manager(path: str):
    p = os.path.abspath(path)
    if sys.platform.startswith("win"):
        os.startfile(p)  # type: ignore
    elif sys.platform == "darwin":
        os.system(f'open "{p}"')
    else:
        os.system(f'xdg-open "{p}"')


try:
    from ui.dialogs import confirm_dialog, TextInputDialog, MultiLineInputDialog
except Exception:
    confirm_dialog = None
    TextInputDialog = None
    MultiLineInputDialog = None


def _split_words(raw: str) -> List[str]:
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
    name = os.path.splitext(os.path.basename(filename))[0]
    for sep in ("_", "-", " "):
        if sep in name:
            name = name.split(sep, 1)[0]
            break
    return (name or "").strip()


def _get_zhuli_audio_dir() -> Path:
    # ✅ 优先使用运行时选择的目录：app_state -> runtime_state.json -> config 默认值
    try:
        d = getattr(app_state, "zhuli_audio_dir", "") or ""
        if d:
            return Path(d)
    except Exception:
        pass

    # 兜底：如果 app_state 还没初始化，直接读 runtime_state.json
    try:
        rt = load_runtime_state() or {}
        d = str(rt.get("zhuli_audio_dir") or "").strip()
        if d:
            return Path(d)
    except Exception:
        pass

    try:
        from config import ZHULI_AUDIO_DIR
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
    """助播关键词管理"""

    sig_realtime_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        # ✅ 启动时同步 runtime_state（解决：重启后目录/模式仍显示旧值）
        try:
            rt = load_runtime_state() or {}
            if rt.get("zhuli_audio_dir"):
                app_state.zhuli_audio_dir = str(rt.get("zhuli_audio_dir"))
            if rt.get("zhuli_mode"):
                app_state.zhuli_mode = str(rt.get("zhuli_mode")).upper()
        except Exception:
            pass

        # ✅ 载入：会自动从 zhuli_keywords.py 迁移到 runtime_state（如果还没有）
        self.data: Dict[str, dict] = load_zhuli_keywords()
        self._normalize_priorities()
        self.current_prefix: str | None = None
        self.new_added_prefixes: set[str] = set()

        # ✅ 自动保存（防抖）
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(300)
        self._autosave_timer.timeout.connect(self._flush_autosave)
        self.sig_realtime_changed.connect(self._schedule_autosave)

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

        # ===== 助播优先模式（A/B） =====
        mode_row = QWidget()
        hr = QHBoxLayout(mode_row)
        hr.setContentsMargins(0, 0, 0, 0)
        hr.setSpacing(10)

        lab = QLabel("优先模式")
        lab.setStyleSheet("font-weight:700;")
        hr.addWidget(lab)

        self.cmb_zhuli_mode = QComboBox()
        self.cmb_zhuli_mode.setObjectName("cmb_zhuli_mode")
        self.cmb_zhuli_mode.setMinimumHeight(34)
        self.cmb_zhuli_mode.setMinimumWidth(260)
        self.cmb_zhuli_mode.setToolTip("模式A：主播关键词优先；模式B：助播关键词优先。选择后立刻生效")
        self.cmb_zhuli_mode.addItem("模式A（主播关键词优先）", "A")
        self.cmb_zhuli_mode.addItem("模式B（助播关键词优先）", "B")

        # 兼容：如果外部没初始化过，也保证有值
        mode = str(getattr(app_state, "zhuli_mode", "A") or "A").upper()
        if mode not in ("A", "B"):
            mode = "A"
        app_state.zhuli_mode = mode

        self.cmb_zhuli_mode.setCurrentIndex(0 if mode == "A" else 1)
        self.cmb_zhuli_mode.setObjectName("ZhuliModeCombo")

        hr.addWidget(self.cmb_zhuli_mode)
        hr.addStretch(1)

        tip = QLabel("切换后实时生效，并自动保存")
        tip.setStyleSheet("color:#93A4B7;")
        hr.addWidget(tip)

        root.addWidget(mode_row)

        # ===== 助播音频目录（像主播一样可选文件夹） =====
        dir_row = QHBoxLayout()
        dir_row.setContentsMargins(0, 0, 0, 0)
        dir_row.setSpacing(10)

        lab_dir = QLabel("助播音频目录")
        lab_dir.setMinimumWidth(92)
        lab_dir.setToolTip("助播关键词触发播放时，会从此目录下按前缀匹配音频")
        dir_row.addWidget(lab_dir)

        self.edt_zhuli_dir = QLineEdit()
        self.edt_zhuli_dir.setObjectName("zhuliDirEdit")
        self.edt_zhuli_dir.setReadOnly(True)
        self.edt_zhuli_dir.setPlaceholderText("未设置，将使用默认 zhuli_audio 目录")
        self.edt_zhuli_dir.setMinimumHeight(34)
        dir_row.addWidget(self.edt_zhuli_dir, 1)

        self.btn_open_zhuli_dir = QPushButton("打开")
        self.btn_open_zhuli_dir.setObjectName("dirBtn")
        self.btn_open_zhuli_dir.setFixedHeight(34)
        self.btn_open_zhuli_dir.setToolTip("在文件管理器中打开当前助播音频目录")
        dir_row.addWidget(self.btn_open_zhuli_dir)

        self.btn_choose_zhuli_dir = QPushButton("选择文件夹")
        self.btn_choose_zhuli_dir.setObjectName("dirBtn")
        self.btn_choose_zhuli_dir.setFixedHeight(34)
        self.btn_choose_zhuli_dir.setToolTip("选择新的助播音频目录，选择后立刻生效")
        dir_row.addWidget(self.btn_choose_zhuli_dir)

        root.addLayout(dir_row)

        def on_mode_changed(_idx: int):
            m = self.cmb_zhuli_mode.currentData()
            if m not in ("A", "B"):
                m = "A"
            app_state.zhuli_mode = m
            self._save_runtime_flag("zhuli_mode", m)
            print(f"✅ 助播模式已切换：{m}（实时生效）")

        self.cmb_zhuli_mode.currentIndexChanged.connect(on_mode_changed)
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
        self.btn_scan_dir.setToolTip("扫描「助播音频目录」下的音频文件名，自动识别前缀并提示是否保存为分类")
        left.addWidget(self.btn_scan_dir)

        # ===== 右侧：词库 =====
        right = QVBoxLayout()
        body.addLayout(right, 5)

        current_row = QHBoxLayout()
        self.lbl_current = QLabel("当前分类：-")
        self.lbl_current.setStyleSheet("font-size: 14px; font-weight: 700;")
        current_row.addWidget(self.lbl_current)
        current_row.addStretch(1)

        right.addLayout(current_row)

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

        # ✅ 助播音频目录：打开/选择
        self.btn_open_zhuli_dir.clicked.connect(self.open_zhuli_dir)
        self.btn_choose_zhuli_dir.clicked.connect(self.choose_zhuli_dir)

        self.refresh_prefix_list()

        self._refresh_zhuli_dir_label()
        self._apply_panel_qss()

    def _apply_panel_qss(self):
        # 仅美化本面板的下拉框/路径框，避免“下拉不清楚”
        self.setStyleSheet(
            '''
            QComboBox#cmb_zhuli_mode, QLineEdit#zhuliDirEdit {
                background: rgba(0,0,0,0.20);
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 8px;
                padding: 6px 10px;
                color: #E6EEF8;
                font-size: 13px;
            }
            QComboBox#cmb_zhuli_mode { padding-right: 34px; }
            QComboBox#cmb_zhuli_mode:hover, QLineEdit#zhuliDirEdit:hover {
                border: 1px solid rgba(255,255,255,0.28);
                background: rgba(0,0,0,0.26);
            }
            QComboBox#cmb_zhuli_mode::drop-down {
                width: 30px;
                border-left: 1px solid rgba(255,255,255,0.12);
                background: rgba(255,255,255,0.06);
                border-top-right-radius: 8px;
                border-bottom-right-radius: 8px;
            }
            QComboBox QAbstractItemView {
                background: rgba(18,22,30,0.98);
                color: #E6EEF8;
                border: 1px solid rgba(255,255,255,0.16);
                selection-background-color: rgba(57,113,249,0.65);
                outline: 0;
                padding: 6px;
            }
            QPushButton#dirBtn {
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,0.16);
                background: rgba(255,255,255,0.06);
                padding: 0 12px;
            }
            QPushButton#dirBtn:hover {
                background: rgba(255,255,255,0.10);
                border: 1px solid rgba(255,255,255,0.22);
            }
            '''
        )

    def _save_runtime_flag(self, key: str, value):
        state = load_runtime_state() or {}
        state[key] = value
        save_runtime_state(state)

    # ===================== 助播音频目录 =====================
    @property
    def zhuli_audio_dir(self) -> str:
        return str(_get_zhuli_audio_dir())

    def _apply_zhuli_dir_to_state(self, path: str, persist: bool = True):
        p = Path(path).expanduser().resolve()
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            # 兜底：回到默认
            p = _get_zhuli_audio_dir().expanduser().resolve()
            p.mkdir(parents=True, exist_ok=True)

        app_state.zhuli_audio_dir = str(p)
        if persist:
            self._save_runtime_flag("zhuli_audio_dir", str(p))

    def _refresh_zhuli_dir_label(self):
        """刷新助播目录显示"""
        cur = str(getattr(app_state, "zhuli_audio_dir", "") or "") or self.zhuli_audio_dir
        if hasattr(self, "edt_zhuli_dir") and self.edt_zhuli_dir is not None:
            self.edt_zhuli_dir.setText(cur)
            self.edt_zhuli_dir.setToolTip(cur)

    def open_zhuli_dir(self):
        """在文件管理器中打开助播音频目录"""
        try:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            p = Path(
                str(getattr(app_state, "zhuli_audio_dir", "") or "") or self.zhuli_audio_dir).expanduser().resolve()
            p.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
        except Exception as e:
            QMessageBox.warning(self, "打开失败", str(e))

    def choose_zhuli_dir(self):
        """选择助播音频目录（选择后立刻生效并保存到 runtime_state）"""
        try:
            from PySide6.QtWidgets import QFileDialog
            start_dir = str(getattr(app_state, "zhuli_audio_dir", "") or "") or self.zhuli_audio_dir
            d = QFileDialog.getExistingDirectory(self, "选择助播音频目录", start_dir)
            if not d:
                return
            self._apply_zhuli_dir_to_state(d, persist=True)
            self._refresh_zhuli_dir_label()
        except Exception as e:
            QMessageBox.warning(self, "选择失败", str(e))

    # ===================== 自动保存（防抖） =====================
    def _schedule_autosave(self, _data: dict):
        # 300ms 内多次修改只保存一次
        self._autosave_timer.start()

    def _flush_autosave(self):
        try:
            self._normalize_priorities()
            save_zhuli_keywords(self.data)
            # 你想看得更明显可以开这行：
            # print(f"💾 助播关键词已自动保存：{len(self.data)} 个分类")
        except Exception as e:
            print("❌ 助播关键词自动保存失败：", e)

    def _normalize_priorities(self):
        # ✅ 去掉“优先级可编辑”：统一锁死为 0（不影响旧数据读取）
        for p, cfg in (self.data or {}).items():
            if isinstance(cfg, dict):
                cfg["priority"] = 0
                cfg.setdefault("prefix", p)

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
            dlg = TextInputDialog(self, "新建分类", "请输入分类名：")
            dlg.exec()
            if not getattr(dlg, "ok", False) or not getattr(dlg, "value", ""):
                return
            name = str(dlg.value).strip()
        else:
            name, ok = QInputDialog.getText(self, "新建分类", "请输入分类名：")
            if not ok:
                return
            name = (name or "").strip()

        if not name or name in self.data:
            return

        self.data[name] = {"priority": 0, "must": [], "any": [], "deny": [], "prefix": name}
        self.new_added_prefixes.add(name)
        self.refresh_prefix_list()

        self._refresh_zhuli_dir_label()
        self._apply_panel_qss()

        # ✅ 关键：新建分类也要实时生效 + 自动保存
        self.sig_realtime_changed.emit(self.data)

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

        if not new_name or new_name == self.current_prefix or new_name in self.data:
            return

        cfg = self.data.pop(self.current_prefix)
        cfg["prefix"] = new_name
        self.data[new_name] = cfg

        if self.current_prefix in self.new_added_prefixes:
            self.new_added_prefixes.remove(self.current_prefix)
            self.new_added_prefixes.add(new_name)

        self.current_prefix = new_name
        self.refresh_prefix_list()

        self._refresh_zhuli_dir_label()
        self._apply_panel_qss()

        # ✅ 关键：重命名也要实时生效 + 自动保存
        self.sig_realtime_changed.emit(self.data)

    def delete_prefix(self):
        if not self.current_prefix:
            return

        if confirm_dialog is not None:
            ok = bool(confirm_dialog(self, "确认删除", f"确定删除分类「{self.current_prefix}」及其全部词条吗？"))
        else:
            ok = QMessageBox.question(self, "确认删除",
                                      f"确定删除分类「{self.current_prefix}」及其全部词条吗？") == QMessageBox.Yes
        if not ok:
            return

        self.data.pop(self.current_prefix, None)
        self.new_added_prefixes.discard(self.current_prefix)
        self.current_prefix = None
        self.refresh_prefix_list()

        self._refresh_zhuli_dir_label()
        self._apply_panel_qss()

        self.sig_realtime_changed.emit(self.data)

    # ===================== 右侧词条操作 =====================
    def _active_key(self):
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

        if MultiLineInputDialog is not None:
            dlg = MultiLineInputDialog(self, f"批量添加{cname}", "支持：换行分隔 / 逗号分隔", default="")
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

        cfg = self.data.get(self.current_prefix) or {"priority": 0, "must": [], "any": [], "deny": [],
                                                     "prefix": self.current_prefix}
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

        if confirm_dialog is not None:
            ok = bool(confirm_dialog(self, "确认清空", f"确定清空分类「{self.current_prefix}」下所有词条吗？"))
        else:
            ok = QMessageBox.question(self, "确认清空",
                                      f"确定清空分类「{self.current_prefix}」下所有词条吗？") == QMessageBox.Yes
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

        if confirm_dialog is not None:
            ok = bool(confirm_dialog(self, "确认导入", "将按“合并”方式导入：同名分类会覆盖/补齐字段。\n确定继续？"))
        else:
            ok = QMessageBox.question(self, "确认导入",
                                      "将按“合并”方式导入：同名分类会覆盖/补齐字段。\n确定继续？") == QMessageBox.Yes
        if not ok:
            return

        self.data = merge_zhuli_keywords(self.data, incoming)
        self._normalize_priorities()
        self.refresh_prefix_list()

        self._refresh_zhuli_dir_label()
        self._apply_panel_qss()

        self.sig_realtime_changed.emit(self.data)

    def save_all(self):
        self._normalize_priorities()
        save_zhuli_keywords(self.data)
        QMessageBox.information(self, "保存成功", "助播关键词已保存（其实你改动时已自动保存）")

    # ===================== 检查目录 =====================
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

        if confirm_dialog is not None:
            ok = bool(confirm_dialog(self, "检查目录", msg))
        else:
            ok = QMessageBox.question(self, "检查目录", msg) == QMessageBox.Yes
        if not ok:
            return

        for name in new_prefixes:
            self.data[name] = {"priority": 0, "must": [], "any": [], "deny": [], "prefix": name}
            self.new_added_prefixes.add(name)

        self.refresh_prefix_list()

        self._refresh_zhuli_dir_label()
        self._apply_panel_qss()

        self.sig_realtime_changed.emit(self.data)

        first = new_prefixes[0]
        for i in range(self.prefix_list.count()):
            if self.prefix_list.item(i).data(Qt.UserRole) == first:
                self.prefix_list.setCurrentRow(i)
                break