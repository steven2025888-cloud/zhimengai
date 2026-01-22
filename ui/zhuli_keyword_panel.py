from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal, QTimer, QUrl
from PySide6.QtGui import QFont, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton,
    QAbstractItemView, QMessageBox, QInputDialog, QFileDialog,
    QFrame,
)

from core.zhuli_keyword_io import load_zhuli_keywords, save_zhuli_keywords, merge_zhuli_keywords
from core.state import app_state

try:
    from ui.dialogs import confirm_dialog, TextInputDialog, MultiLineInputDialog
except Exception:
    confirm_dialog = None
    TextInputDialog = None
    MultiLineInputDialog = None


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
        pass


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


def _get_zhuli_audio_dir() -> Path:
    """
    ✅ 优先使用运行时选择的目录：
    app_state.zhuli_audio_dir -> runtime_state.json -> config 默认值 -> ./zhuli_audio
    """
    try:
        d = getattr(app_state, "zhuli_audio_dir", "") or ""
        if d:
            return Path(d)
    except Exception:
        pass

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


def _get_supported_audio_exts() -> tuple:
    try:
        from config import SUPPORTED_AUDIO_EXTS
        exts = tuple(str(e).lower() for e in SUPPORTED_AUDIO_EXTS)
        return exts if exts else (".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg")
    except Exception:
        return (".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg")


def _get_help_url() -> str:
    """
    从 config 读取帮助文档 URL（任意一个存在即可）：
    - ZHULI_HELP_URL
    - ZHULI_DOC_URL
    - HELP_ZHULI_URL
    - HELP_DOC_URL
    """
    try:
        import config  # type: ignore
        for k in ("ZHULI_HELP_URL", "ZHULI_DOC_URL", "HELP_ZHULI_URL", "HELP_DOC_URL"):
            v = getattr(config, k, "")
            if isinstance(v, str) and v.strip():
                return v.strip()
    except Exception:
        pass
    return ""


class ZhuliKeywordPanel(QWidget):
    """
    助播设置（深色主题适配、美化版）：

    - 左侧：分类（= 助播音频目录下的文件夹名）
    - 右侧：包含词 must（= 主播音频文件名去扩展名，包含即可触发）
    - 当“播完某条音频”且音频文件名包含任意包含词 => 下一条随机播放该分类文件夹内的助播音频
    """

    sig_realtime_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("助播设置")

        # ✅ runtime_state：还原助播目录
        try:
            rt = load_runtime_state() or {}
            if rt.get("zhuli_audio_dir"):
                app_state.zhuli_audio_dir = str(rt.get("zhuli_audio_dir"))
        except Exception:
            pass

        self.data: Dict[str, dict] = load_zhuli_keywords() or {}
        self.current_prefix: Optional[str] = None
        self.new_added_prefixes: set = set()
        self._sanitize_all()

        # ✅ 自动保存（防抖）
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(300)
        self._autosave_timer.timeout.connect(self._flush_autosave)
        self.sig_realtime_changed.connect(self._schedule_autosave)

        self._build_ui()
        self._apply_styles()

        self.refresh_prefix_list()
        self._refresh_zhuli_dir_label()

    # ===================== UI =====================

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # ===== 顶部标题 + 帮助 =====
        header = QHBoxLayout()
        title = QLabel("助播设置")
        title.setFont(QFont("微软雅黑", 16, QFont.Bold))
        header.addWidget(title)

        sub = QLabel("（播完主播音频后自动接一句）")
        sub.setObjectName("SubTitle")
        header.addWidget(sub)
        header.addStretch(1)

        self.btn_help_top = QPushButton("？")
        self.btn_help_top.setObjectName("HelpBtn")
        self.btn_help_top.setFixedSize(28, 28)
        self.btn_help_top.setToolTip("打开说明文档")
        self.btn_help_top.clicked.connect(self.open_help_doc)
        header.addWidget(self.btn_help_top)

        root.addLayout(header)

        # ===== 卡片：目录 =====
        dir_card = QFrame()
        dir_card.setObjectName("Card")
        dir_layout = QVBoxLayout(dir_card)
        dir_layout.setContentsMargins(12, 10, 12, 10)
        dir_layout.setSpacing(10)

        dir_title_row = QHBoxLayout()
        lab_dir = QLabel("助播音频目录")
        lab_dir.setObjectName("CardTitle")
        lab_dir.setToolTip("助播触发时，会从「助播音频目录/分类文件夹」里随机挑选音频")
        dir_title_row.addWidget(lab_dir)
        dir_title_row.addStretch(1)

        self.btn_open_zhuli_dir = QPushButton("打开文件夹")
        self.btn_open_zhuli_dir.setObjectName("SecondaryBtn")
        self.btn_open_zhuli_dir.setFixedHeight(34)
        self.btn_open_zhuli_dir.clicked.connect(self.open_zhuli_dir)
        dir_title_row.addWidget(self.btn_open_zhuli_dir)


        self.btn_scan_dir = QPushButton("检查目录")
        self.btn_scan_dir.setObjectName("PrimaryBtn")
        self.btn_scan_dir.setFixedHeight(36)
        self.btn_scan_dir.setToolTip(
            "扫描「助播音频目录」下的所有分类文件夹（一级子目录）。\n"
            "自动生成：分类=文件夹名，包含词默认填同名。\n"
            "（你也可以把包含词改成更容易命中的关键词，比如“上车”“挂链接”“尺寸”）"
        )
        self.btn_scan_dir.clicked.connect(self.scan_zhuli_audio_dir)

        dir_title_row.addWidget(self.btn_scan_dir)
        dir_layout.addLayout(dir_title_row)

        dir_row = QHBoxLayout()
        self.edt_zhuli_dir = QLineEdit()
        self.edt_zhuli_dir.setReadOnly(True)
        self.edt_zhuli_dir.setPlaceholderText("未设置，将使用默认 zhuli_audio 目录")
        self.edt_zhuli_dir.setMinimumHeight(36)
        self.edt_zhuli_dir.setObjectName("PathEdit")
        dir_row.addWidget(self.edt_zhuli_dir, 1)

        self.btn_choose_zhuli_dir = QPushButton("选择目录")
        self.btn_choose_zhuli_dir.setObjectName("PrimaryBtn")
        self.btn_choose_zhuli_dir.setFixedHeight(34)
        self.btn_choose_zhuli_dir.clicked.connect(self.choose_zhuli_dir)
        dir_row.addWidget(self.btn_choose_zhuli_dir,0.5)

        dir_layout.addLayout(dir_row)
        root.addWidget(dir_card)

        # ===== 主体（左右卡片）=====
        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        # --- 左侧：分类 ---
        left_card = QFrame()
        left_card.setObjectName("Card")
        left = QVBoxLayout(left_card)
        left.setContentsMargins(12, 10, 12, 10)
        left.setSpacing(10)
        body.addWidget(left_card, 2)

        left_top = QHBoxLayout()
        lab_left = QLabel("分类（文件夹）")
        lab_left.setObjectName("CardTitle")
        left_top.addWidget(lab_left)
        left_top.addStretch(1)
        left.addLayout(left_top)

        self.lbl_current_left = QLabel("当前：-")
        self.lbl_current_left.setObjectName("Pill")
        self.lbl_current_left.setToolTip("当前正在编辑的分类")
        left.addWidget(self.lbl_current_left)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索分类…")
        self.search.setObjectName("SearchEdit")
        self.search.textChanged.connect(lambda _: self.refresh_prefix_list())
        left.addWidget(self.search)

        self.prefix_list = QListWidget()
        self.prefix_list.setObjectName("List")
        self.prefix_list.setSpacing(6)
        self.prefix_list.itemSelectionChanged.connect(self.on_select_prefix)
        left.addWidget(self.prefix_list, 1)

        left_ops = QHBoxLayout()
        self.btn_add_prefix = QPushButton("＋ 新增")
        self.btn_rename_prefix = QPushButton("✎ 重命名")
        self.btn_del_prefix = QPushButton("🗑 删除")
        for b in (self.btn_add_prefix, self.btn_rename_prefix, self.btn_del_prefix):
            b.setFixedHeight(34)
            b.setObjectName("SecondaryBtn")
        self.btn_del_prefix.setObjectName("DangerBtn")

        self.btn_add_prefix.clicked.connect(self.add_prefix)
        self.btn_rename_prefix.clicked.connect(self.rename_prefix)
        self.btn_del_prefix.clicked.connect(self.delete_prefix)

        left_ops.addWidget(self.btn_add_prefix)
        left_ops.addWidget(self.btn_rename_prefix)
        left_ops.addWidget(self.btn_del_prefix)
        left.addLayout(left_ops)

        # --- 右侧：包含词 ---
        right_card = QFrame()
        right_card.setObjectName("Card")
        right = QVBoxLayout(right_card)
        right.setContentsMargins(12, 10, 12, 10)
        right.setSpacing(10)
        body.addWidget(right_card, 5)

        right_head = QHBoxLayout()
        right_title = QLabel("包含词（音频名包含即可触发）")
        right_title.setObjectName("CardTitle")
        right_head.addWidget(right_title)
        right_head.addStretch(1)

        self.btn_help_right = QPushButton("？")
        self.btn_help_right.setObjectName("HelpBtn")
        self.btn_help_right.setFixedSize(28, 28)
        self.btn_help_right.setToolTip("打开说明文档")
        self.btn_help_right.clicked.connect(self.open_help_doc)
        right_head.addWidget(self.btn_help_right)
        right.addLayout(right_head)

        hint = QLabel(
            "提示：包含词填“音频名里会出现的关键词（去掉 .mp3/.wav 等后缀）”。\n"
            "规则：只要主播音频名包含该词，就会触发本分类。\n"
            "示例：主播播放“上车挂链接.mp3” → 包含词写“上车”或“挂链接”，播完后自动随机播放分类里的助播音频（例如：好的，已上车）。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("HintBox")
        right.addWidget(hint)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("Sep")
        right.addWidget(sep)

        self.must_list = QListWidget()
        self.must_list.setObjectName("List")
        self.must_list.setSpacing(6)
        self.must_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        right.addWidget(self.must_list, 1)

        ops1 = QHBoxLayout()
        self.btn_batch_add = QPushButton("批量添加")
        self.btn_del_selected = QPushButton("删除选中")
        self.btn_clear_list = QPushButton("清空列表")
        self.btn_clear_prefix = QPushButton("清空本分类")
        for b in (self.btn_batch_add, self.btn_del_selected, self.btn_clear_list, self.btn_clear_prefix):
            b.setFixedHeight(34)
            b.setObjectName("SecondaryBtn")
        self.btn_clear_prefix.setObjectName("DangerBtn")

        self.btn_batch_add.clicked.connect(self.batch_add_words)
        self.btn_del_selected.clicked.connect(self.delete_selected_words)
        self.btn_clear_list.clicked.connect(self.clear_current_list)
        self.btn_clear_prefix.clicked.connect(self.clear_current_prefix)

        ops1.addWidget(self.btn_batch_add)
        ops1.addWidget(self.btn_del_selected)
        ops1.addWidget(self.btn_clear_list)
        ops1.addWidget(self.btn_clear_prefix)
        ops1.addStretch(1)
        right.addLayout(ops1)

        ops2 = QHBoxLayout()
        ops2.addStretch(1)

        self.btn_import = QPushButton("导入")
        self.btn_export = QPushButton("导出")
        self.btn_save = QPushButton("保存")

        self.btn_import.setObjectName("SecondaryBtn")
        self.btn_export.setObjectName("SecondaryBtn")
        self.btn_save.setObjectName("PrimaryBtn")

        for b in (self.btn_import, self.btn_export, self.btn_save):
            b.setFixedHeight(36)

        self.btn_export.clicked.connect(self.export_json)
        self.btn_import.clicked.connect(self.import_merge_json)
        self.btn_save.clicked.connect(self.save_all)

        ops2.addWidget(self.btn_import)
        ops2.addWidget(self.btn_export)
        ops2.addWidget(self.btn_save)
        right.addLayout(ops2)

    def _apply_styles(self):
        """
        深色主题适配：
        - 尽量复用全局 QSS
        - 这里只给本面板新增少量“自定义组件”的样式（帮助按钮/提示框/胶囊标签/次要按钮）
        """
        self.setAttribute(Qt.WA_StyledBackground, True)

        # 注意：不写 QWidget {color:...}，避免和你全局深色主题冲突
        self.setStyleSheet(
            """
            QLabel#SubTitle{
                color: rgba(230,238,248,0.65);
                margin-left: 6px;
            }

            QFrame#Card{
                background: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 14px;
            }
            QLabel#CardTitle{
                font-weight: 800;
            }

            QLabel#Pill{
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 10px;
                padding: 4px 10px;
            }

            QLabel#HintBox{
                background: rgba(43,127,255,0.12);
                border: 1px solid rgba(43,127,255,0.28);
                border-radius: 12px;
                padding: 10px 12px;
            }

            QPushButton#HelpBtn{
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
                font-weight: 900;
                min-width: 28px;
                min-height: 28px;
            }
            QPushButton#HelpBtn:hover{ background: rgba(255,255,255,0.10); border-color: rgba(255,255,255,0.18); }
            QPushButton#HelpBtn:pressed{ background: rgba(255,255,255,0.05); }

            QPushButton#SecondaryBtn{
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.10);
                font-weight: 700;
            }
            QPushButton#SecondaryBtn:hover{ background: rgba(255,255,255,0.10); border-color: rgba(255,255,255,0.18); }
            QPushButton#SecondaryBtn:pressed{ background: rgba(255,255,255,0.05); }

            QPushButton#PrimaryBtn{
                font-weight: 800;
            }

            QPushButton#DangerBtn{
                background: rgba(239,68,68,0.18);
                border: 1px solid rgba(239,68,68,0.35);
                font-weight: 900;
            }
            QPushButton#DangerBtn:hover{ background: rgba(239,68,68,0.26); border-color: rgba(239,68,68,0.45); }

            QLineEdit#SearchEdit, QLineEdit#PathEdit{
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 10px;
                padding: 6px 10px;
            }

            QListWidget#List{
                background: rgba(255,255,255,0.02);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 12px;
                padding: 6px;
            }
            """
        )

    # ===================== 帮助 =====================

    def open_help_doc(self):
        url = _get_help_url()
        if not url:
            msg = "请在 config.py 中配置 ZHULI_HELP_URL（或 ZHULI_DOC_URL / HELP_ZHULI_URL / HELP_DOC_URL）"
            if confirm_dialog:
                confirm_dialog(self, "未配置说明文档", msg)
            else:
                confirm_dialog(self, "未配置说明文档", msg)
            return
        try:
            QDesktopServices.openUrl(QUrl(url))
        except Exception as e:
            confirm_dialog(self, "打开失败", str(e))

    # ===================== 目录：打开/选择 =====================

    @property
    def zhuli_audio_dir(self) -> str:
        return str(_get_zhuli_audio_dir())

    def _save_runtime_flag(self, key: str, value):
        state = load_runtime_state() or {}
        state[key] = value
        save_runtime_state(state)

    def _apply_zhuli_dir_to_state(self, path: str, persist: bool = True):
        p = Path(path).expanduser().resolve()
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            p = _get_zhuli_audio_dir().expanduser().resolve()
            p.mkdir(parents=True, exist_ok=True)

        app_state.zhuli_audio_dir = str(p)
        if persist:
            self._save_runtime_flag("zhuli_audio_dir", str(p))

    def _refresh_zhuli_dir_label(self):
        cur = str(getattr(app_state, "zhuli_audio_dir", "") or "") or self.zhuli_audio_dir
        self.edt_zhuli_dir.setText(cur)
        self.edt_zhuli_dir.setToolTip(cur)

    def open_zhuli_dir(self):
        try:
            p = Path(str(getattr(app_state, "zhuli_audio_dir", "") or "") or self.zhuli_audio_dir).expanduser().resolve()
            p.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
        except Exception as e:
            if confirm_dialog:
                confirm_dialog(self, "打开失败", str(e))
            else:
                confirm_dialog(self, "打开失败", str(e))

    def choose_zhuli_dir(self):
        try:
            start_dir = str(getattr(app_state, "zhuli_audio_dir", "") or "") or self.zhuli_audio_dir
            d = QFileDialog.getExistingDirectory(self, "选择助播音频目录", start_dir)
            if not d:
                return
            self._apply_zhuli_dir_to_state(d, persist=True)
            self._refresh_zhuli_dir_label()
        except Exception as e:
            if confirm_dialog:
                confirm_dialog(self, "选择失败", str(e))
            else:
                confirm_dialog(self, "选择失败", str(e))

    # ===================== 自动保存（防抖） =====================

    def _schedule_autosave(self, _data: dict):
        self._autosave_timer.start()

    def _flush_autosave(self):
        try:
            self._sanitize_all()
            save_zhuli_keywords(self.data)
        except Exception as e:
            print("❌ 助播关键词自动保存失败：", e)

    # ===================== 数据清洗：只保留 must =====================

    def _sanitize_cfg(self, prefix: str, cfg: Optional[dict]) -> dict:
        cfg = cfg if isinstance(cfg, dict) else {}
        must = cfg.get("must", []) or []
        if not isinstance(must, list):
            must = [str(must)]
        must = _dedup_keep_order(list(map(str, must)))
        return {
            "priority": 0,
            "prefix": str(cfg.get("prefix") or prefix or "").strip() or prefix,
            "must": must,
        }

    def _sanitize_all(self):
        out: Dict[str, dict] = {}
        for p, cfg in (self.data or {}).items():
            p = str(p).strip()
            if not p:
                continue
            out[p] = self._sanitize_cfg(p, cfg if isinstance(cfg, dict) else {})
        self.data = out

    # ===================== 左侧分类 =====================

    def refresh_prefix_list(self):
        keyword = (self.search.text() or "").strip()
        keep = self.current_prefix

        self.prefix_list.blockSignals(True)
        self.prefix_list.clear()

        all_prefixes = list((self.data or {}).keys())
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
            self.lbl_current_left.setText("当前：-")
            self.must_list.clear()

    def on_select_prefix(self):
        items = self.prefix_list.selectedItems()
        if not items:
            return
        prefix = items[0].data(Qt.UserRole)
        self.current_prefix = prefix
        self.lbl_current_left.setText(f"当前：{prefix}")
        self._render_prefix(prefix)

    def add_prefix(self):
        name = None
        if TextInputDialog is not None:
            dlg = TextInputDialog(self, "新增分类", "请输入分类名：", default="")
            dlg.exec()
            if not getattr(dlg, "ok", False) or not getattr(dlg, "value", ""):
                return
            name = str(dlg.value).strip()
        else:
            name, ok = QInputDialog.getText(self, "新增分类", "请输入分类名：")
            if not ok:
                return
            name = (name or "").strip()

        if not name or name in self.data:
            return

        self.data[name] = {"priority": 0, "must": [], "prefix": name}
        self.new_added_prefixes.add(name)
        self.refresh_prefix_list()
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

        cfg = self.data.pop(self.current_prefix, {})
        cfg["prefix"] = new_name
        self.data[new_name] = self._sanitize_cfg(new_name, cfg)

        if self.current_prefix in self.new_added_prefixes:
            self.new_added_prefixes.remove(self.current_prefix)
            self.new_added_prefixes.add(new_name)

        self.current_prefix = new_name
        self.refresh_prefix_list()
        self.sig_realtime_changed.emit(self.data)

    def delete_prefix(self):
        if not self.current_prefix:
            return

        msg = f"确定删除分类「{self.current_prefix}」及其全部包含词吗？"
        if confirm_dialog is not None:
            ok = bool(confirm_dialog(self, "确认删除", msg))
        else:
            ok = QMessageBox.question(self, "确认删除", msg) == QMessageBox.Yes
        if not ok:
            return

        self.data.pop(self.current_prefix, None)
        self.new_added_prefixes.discard(self.current_prefix)
        self.current_prefix = None
        self.refresh_prefix_list()
        self.sig_realtime_changed.emit(self.data)

    # ===================== 右侧词条操作 =====================

    def _render_prefix(self, prefix: str):
        cfg = self._sanitize_cfg(prefix, self.data.get(prefix))
        self.data[prefix] = cfg

        self.must_list.clear()
        for w in cfg.get("must", []) or []:
            self.must_list.addItem(QListWidgetItem(str(w)))

    def batch_add_words(self):
        if not self.current_prefix:
            return

        if MultiLineInputDialog is not None:
            dlg = MultiLineInputDialog(self, "批量添加包含词", "支持：换行分隔 / 逗号分隔", default="")
            dlg.exec()
            if not getattr(dlg, "ok", False):
                return
            text = getattr(dlg, "text", "")
        else:
            text, ok = QInputDialog.getMultiLineText(self, "批量添加包含词", "每行一个（或逗号分隔）：")
            if not ok:
                return
            text = text or ""

        words = _split_words(text)
        if not words:
            return

        cfg = self._sanitize_cfg(self.current_prefix, self.data.get(self.current_prefix))
        arr = list(map(str, cfg.get("must", []) or []))
        arr.extend(words)
        cfg["must"] = _dedup_keep_order(arr)
        self.data[self.current_prefix] = cfg

        self._render_prefix(self.current_prefix)
        self.sig_realtime_changed.emit(self.data)

    def delete_selected_words(self):
        if not self.current_prefix:
            return

        items = self.must_list.selectedItems()
        if not items:
            return

        msg = f"确定删除选中的 {len(items)} 个包含词吗？"
        if confirm_dialog is not None:
            ok = bool(confirm_dialog(self, "确认删除", msg))
        else:
            ok = QMessageBox.question(self, "确认删除", msg) == QMessageBox.Yes
        if not ok:
            return

        selected = set(i.text() for i in items)
        cfg = self._sanitize_cfg(self.current_prefix, self.data.get(self.current_prefix))
        cfg["must"] = [w for w in (cfg.get("must", []) or []) if str(w) not in selected]
        self.data[self.current_prefix] = cfg

        self._render_prefix(self.current_prefix)
        self.sig_realtime_changed.emit(self.data)

    def clear_current_list(self):
        if not self.current_prefix:
            return
        cfg = self._sanitize_cfg(self.current_prefix, self.data.get(self.current_prefix))
        cfg["must"] = []
        self.data[self.current_prefix] = cfg
        self._render_prefix(self.current_prefix)
        self.sig_realtime_changed.emit(self.data)

    def clear_current_prefix(self):
        self.clear_current_list()

    # ===================== 导入 / 导出 / 保存 =====================

    def export_json(self):
        try:
            self._sanitize_all()
            path, _ = QFileDialog.getSaveFileName(self, "导出助播设置", "", "JSON (*.json)")
            if not path:
                return
            Path(path).write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            if confirm_dialog:
                confirm_dialog(self, "导出成功", f"已导出：{path}")
            else:
                confirm_dialog(self, "导出成功", f"已导出：{path}")
        except Exception as e:
            if confirm_dialog:
                confirm_dialog(self, "导出失败", str(e))
            else:
                confirm_dialog(self, "导出失败", str(e))

    def import_merge_json(self):
        try:
            path, _ = QFileDialog.getOpenFileName(self, "导入助播设置（合并）", "", "JSON (*.json)")
            if not path:
                return
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                if confirm_dialog:
                    confirm_dialog(self, "导入失败", "文件内容不是 JSON 对象")
                else:
                    confirm_dialog(self, "导入失败", "文件内容不是 JSON 对象")
                return

            merged = merge_zhuli_keywords(self.data, raw) if callable(merge_zhuli_keywords) else {**self.data, **raw}
            self.data = merged or {}
            self._sanitize_all()

            self.new_added_prefixes.clear()
            self.refresh_prefix_list()
            self.sig_realtime_changed.emit(self.data)

            msg = "已合并导入（旧字段会自动丢弃，仅保留包含词）。"
            if confirm_dialog:
                confirm_dialog(self, "导入成功", msg)
            else:
                confirm_dialog(self, "导入成功", msg)

        except Exception as e:
            if confirm_dialog:
                confirm_dialog(self, "导入失败", str(e))
            else:
                confirm_dialog(self, "导入失败", str(e))

    def save_all(self):
        try:
            self._sanitize_all()
            save_zhuli_keywords(self.data)
            self.new_added_prefixes.clear()
            self.refresh_prefix_list()
            if confirm_dialog:
                confirm_dialog(self, "保存成功", "助播设置已保存")
            else:
                confirm_dialog(self, "保存成功", "助播设置已保存")
        except Exception as e:
            if confirm_dialog:
                confirm_dialog(self, "保存失败", str(e))
            else:
                confirm_dialog(self, "保存失败", str(e))

    # ===================== 检查目录：扫描分类文件夹并自动生成设置 =====================

    def scan_zhuli_audio_dir(self):
        base = Path(str(getattr(app_state, "zhuli_audio_dir", "") or "") or self.zhuli_audio_dir).expanduser().resolve()
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        exts = _get_supported_audio_exts()
        added = 0
        updated = 0

        try:
            for d in sorted([p for p in base.iterdir() if p.is_dir()], key=lambda x: x.name.lower()):
                name = d.name.strip()
                if not name or name.startswith("."):
                    continue

                # 只把“包含音频”的文件夹当分类
                has_audio = False
                try:
                    for p in d.rglob("*"):
                        if p.is_file() and p.suffix.lower() in exts:
                            has_audio = True
                            break
                except Exception:
                    continue
                if not has_audio:
                    continue

                if name not in self.data:
                    self.data[name] = {"priority": 0, "prefix": name, "must": [name]}
                    self.new_added_prefixes.add(name)
                    added += 1
                else:
                    cfg = self._sanitize_cfg(name, self.data.get(name))
                    if not (cfg.get("must") or []):
                        cfg["must"] = [name]
                        self.data[name] = cfg
                        updated += 1

        except Exception as e:
            if confirm_dialog:
                confirm_dialog(self, "检查失败", str(e))
            else:
                confirm_dialog(self, "检查失败", str(e))
            return

        self._sanitize_all()
        self.refresh_prefix_list()
        self.sig_realtime_changed.emit(self.data)

        msg = (
            f"扫描目录：{str(base)}\n"
            f"新增分类：{added}\n"
            f"补全包含词：{updated}\n\n"
            f"小提示：你可以把某个分类的包含词改成更容易命中的关键词（音频名里出现就行）。\n"
            f"例如：分类=上车回复，包含词=上车 或 挂链接；当主播播放“上车挂链接.mp3”时，会随机触发该分类文件夹里的助播音频（例如：好的，已上车）。"
        )
        if confirm_dialog:
            confirm_dialog(self, "检查完成", msg)
        else:
            confirm_dialog(self, "检查完成", msg)
