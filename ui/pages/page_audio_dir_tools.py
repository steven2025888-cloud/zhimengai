# ui/pages/page_audio_dir_tools.py
import os
import re
import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QMessageBox, QSizePolicy, QFrame, QComboBox
)

from core.state import app_state
from core.audio_tools import reorder_audio_files, smart_split_audio_to_dir
from config import AUDIO_BASE_DIR, ZHULI_AUDIO_DIR, other_gz_audio, other_dz_audio, SUPPORTED_AUDIO_EXTS
from ui.dialogs import confirm_dialog, int_input_dialog


def _ensure_dir(p: str) -> str:
    p = str(p or "").strip()
    if not p:
        return ""
    try:
        os.makedirs(p, exist_ok=True)
        return p
    except Exception:
        return ""


def _is_audio_file(fp: str) -> bool:
    try:
        ext = os.path.splitext(fp)[1].lower()
        return ext in tuple(str(e).lower() for e in SUPPORTED_AUDIO_EXTS)
    except Exception:
        return False


def _audio_filter() -> str:
    # "音频文件 (*.mp3 *.wav ...)"
    try:
        exts = [f"*{e}" for e in SUPPORTED_AUDIO_EXTS]
    except Exception:
        exts = ["*.mp3", "*.wav", "*.m4a", "*.aac", "*.flac", "*.ogg"]
    return f"音频文件 ({' '.join(exts)})"


class _Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Plain)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        if title:
            t = QLabel(title)
            t.setObjectName("CardTitle")
            root.addWidget(t)

        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("CardSubTitle")
            s.setWordWrap(True)
            root.addWidget(s)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(10)
        root.addLayout(self.body)


class _DirRow(QWidget):
    def __init__(self, title: str, default_path: str, on_change=None, parent=None):
        super().__init__(parent)
        self.default_path = str(default_path)
        self._on_change = on_change

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.lbl = QLabel(title)
        self.lbl.setFixedWidth(90)
        lay.addWidget(self.lbl)

        self.edt = QLineEdit()
        self.edt.setPlaceholderText("请选择目录…")
        lay.addWidget(self.edt, 1)

        self.btn_pick = QPushButton("选择")
        self.btn_open = QPushButton("打开")
        self.btn_reset = QPushButton("默认")
        lay.addWidget(self.btn_pick)
        lay.addWidget(self.btn_open)
        lay.addWidget(self.btn_reset)

        self.btn_pick.clicked.connect(self.pick_dir)
        self.btn_open.clicked.connect(self.open_dir)
        self.btn_reset.clicked.connect(self.reset_default)
        self.edt.editingFinished.connect(self._emit_change)

    def _emit_change(self):
        if callable(self._on_change):
            self._on_change()

    def set_value(self, path: str):
        self.edt.setText(str(path or ""))

    def value(self) -> str:
        return str(self.edt.text() or "").strip()

    def pick_dir(self):
        cur = self.value() or self.default_path
        path = QFileDialog.getExistingDirectory(self, "选择目录", cur)
        if path:
            self.edt.setText(path)
            self._emit_change()

    def open_dir(self):
        p = self.value() or self.default_path
        p = _ensure_dir(p) or p
        if not p or not os.path.isdir(p):
            QMessageBox.warning(self, "提示", "目录无效，请先选择一个有效目录。")
            return
        os.startfile(p)

    def reset_default(self):
        self.edt.setText(self.default_path)
        self._emit_change()


class AudioDirToolsPage(QWidget):
    """
    音频资源管理（音频目录工具）：
    - 目录设置：主播/助播/关注/点赞（保存到 runtime_state.json，并同步到 app_state）
    - 工具：排序 / 复制 / 自动裁剪（作用目录可选）
    """

    def __init__(self, ctx: dict):
        super().__init__()
        self.ctx = ctx
        self.save_runtime_flag = ctx.get("save_runtime_flag")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self._apply_local_style()

        title = QLabel("音频资源管理")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        tip = QLabel("设置四类音频目录（会写入 runtime_state.json），并对任意目录执行排序 / 复制 / 自动裁剪。")
        tip.setObjectName("PageTip")
        tip.setWordWrap(True)
        root.addWidget(tip)

        # ===== 卡片：目录设置 =====
        self.card_dirs = _Card(
            "目录设置",
            "关注/点赞目录修改后，建议点击“保存并应用”。已排队的旧音频会被清空，后续触发立即使用新目录。",
        )
        root.addWidget(self.card_dirs)

        self.row_anchor = _DirRow("主播目录", str(AUDIO_BASE_DIR), on_change=self._preview_apply_dirs)
        self.row_zhuli = _DirRow("助播目录", str(ZHULI_AUDIO_DIR), on_change=self._preview_apply_dirs)
        self.row_follow = _DirRow("关注目录", str(other_gz_audio), on_change=self._preview_apply_dirs)
        self.row_like = _DirRow("点赞目录", str(other_dz_audio), on_change=self._preview_apply_dirs)

        self.card_dirs.body.addWidget(self.row_anchor)
        self.card_dirs.body.addWidget(self.row_zhuli)
        self.card_dirs.body.addWidget(self.row_follow)
        self.card_dirs.body.addWidget(self.row_like)

        row_btns = QHBoxLayout()
        row_btns.addStretch(1)

        self.btn_reload = QPushButton("从当前状态刷新")
        self.btn_save = QPushButton("保存并应用")
        self.btn_reload.setFixedWidth(150)
        self.btn_save.setFixedWidth(130)

        row_btns.addWidget(self.btn_reload)
        row_btns.addWidget(self.btn_save)
        self.card_dirs.body.addLayout(row_btns)

        self.btn_save.clicked.connect(self.on_save_dirs)
        self.btn_reload.clicked.connect(self.load_from_state)

        # ===== 卡片：工具 =====
        self.card_tools = _Card("音频工具", "选择“工具作用目录”，再执行对应操作。复制音频：选择一个音频文件 → 输入份数 → 自动续号复制。")
        root.addWidget(self.card_tools)

        tool_row = QHBoxLayout()
        tool_row.setSpacing(10)

        lbl = QLabel("工具作用目录：")
        lbl.setFixedWidth(95)
        tool_row.addWidget(lbl)

        self.cmb_target = QComboBox()
        self.cmb_target.addItems(["主播目录", "助播目录", "关注目录", "点赞目录"])
        self.cmb_target.setFixedWidth(140)
        self.cmb_target.currentIndexChanged.connect(self._update_target_path)
        tool_row.addWidget(self.cmb_target)

        self.lbl_target_path = QLabel("")
        self.lbl_target_path.setObjectName("PathHint")
        self.lbl_target_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        tool_row.addWidget(self.lbl_target_path, 1)

        self.btn_open_target = QPushButton("打开作用目录")
        self.btn_open_target.setFixedWidth(120)
        self.btn_open_target.clicked.connect(self._open_target_dir)
        tool_row.addWidget(self.btn_open_target)

        self.card_tools.body.addLayout(tool_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.btn_reorder = QPushButton("🧹 排序音频")
        self.btn_copy = QPushButton("📁 复制音频")
        self.btn_split = QPushButton("✂️ 自动裁剪")

        for b in (self.btn_reorder, self.btn_copy, self.btn_split):
            b.setMinimumSize(150, 40)
            b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn_row.addWidget(b)

        btn_row.addStretch(1)
        self.card_tools.body.addLayout(btn_row)

        root.addStretch(1)

        self.btn_reorder.clicked.connect(self.handle_reorder_audio)
        self.btn_copy.clicked.connect(self.handle_copy_audio)
        self.btn_split.clicked.connect(self.handle_split_audio)

        self.load_from_state()
        self._update_target_path()

    # ===================== 样式 =====================

    def _apply_local_style(self):
        # 只给该页面的控件做深色优化（避免影响全局 QSS）
        self.setStyleSheet("""
        QLabel#PageTitle { font-size: 18px; font-weight: 800; }
        QLabel#PageTip { color: #A9A9A9; }

        QFrame#Card {
            background: #1F1F1F;
            border: 1px solid #343434;
            border-radius: 14px;
        }
        QLabel#CardTitle { font-size: 14px; font-weight: 800; }
        QLabel#CardSubTitle { color: #9A9A9A; }

        QLabel#PathHint { color: #B8B8B8; }

        QLineEdit {
            color: #EDEDED;
            background: #262626;
            border: 1px solid #3A3A3A;
            border-radius: 10px;
            padding: 8px 10px;
        }
        QLineEdit:focus { border: 1px solid #5A5A5A; }

        QPushButton {
            color: #EDEDED;
            background: #2B2B2B;
            border: 1px solid #3A3A3A;
            border-radius: 10px;
            padding: 8px 12px;
        }
        QPushButton:hover { background: #333333; border: 1px solid #4A4A4A; }
        QPushButton:pressed { background: #222222; }

        QComboBox {
            color: #EDEDED;
            background: #262626;
            border: 1px solid #3A3A3A;
            border-radius: 10px;
            padding: 8px 10px;
        }
        QComboBox:hover { border: 1px solid #4A4A4A; }
        QComboBox::drop-down { border: none; width: 26px; }
        QComboBox QAbstractItemView {
            background: #262626;
            color: #EDEDED;
            border: 1px solid #3A3A3A;
            selection-background-color: #3A3A3A;
            outline: 0;
        }
        """)

    # ===================== 目录设置 =====================

    def load_from_state(self):
        self.row_anchor.set_value(getattr(app_state, "anchor_audio_dir", str(AUDIO_BASE_DIR)))
        self.row_zhuli.set_value(getattr(app_state, "zhuli_audio_dir", str(ZHULI_AUDIO_DIR)))
        self.row_follow.set_value(getattr(app_state, "follow_audio_dir", str(other_gz_audio)))
        self.row_like.set_value(getattr(app_state, "like_audio_dir", str(other_dz_audio)))
        self._update_target_path()

    def _preview_apply_dirs(self):
        # 只做“预览应用”（不写 runtime），解决你说的：换了目录但马上触发还是旧的（其实常见是队列里已有旧音频）
        app_state.anchor_audio_dir = self.row_anchor.value() or str(AUDIO_BASE_DIR)
        app_state.zhuli_audio_dir = self.row_zhuli.value() or str(ZHULI_AUDIO_DIR)
        app_state.follow_audio_dir = self.row_follow.value() or str(other_gz_audio)
        app_state.like_audio_dir = self.row_like.value() or str(other_dz_audio)
        self._update_target_path()

    def on_save_dirs(self):
        anchor = _ensure_dir(self.row_anchor.value() or str(AUDIO_BASE_DIR)) or str(AUDIO_BASE_DIR)
        zhuli = _ensure_dir(self.row_zhuli.value() or str(ZHULI_AUDIO_DIR)) or str(ZHULI_AUDIO_DIR)
        follow = _ensure_dir(self.row_follow.value() or str(other_gz_audio)) or str(other_gz_audio)
        like = _ensure_dir(self.row_like.value() or str(other_dz_audio)) or str(other_dz_audio)

        if callable(self.save_runtime_flag):
            self.save_runtime_flag("anchor_audio_dir", anchor)
            self.save_runtime_flag("zhuli_audio_dir", zhuli)
            self.save_runtime_flag("follow_audio_dir", follow)
            self.save_runtime_flag("like_audio_dir", like)

        app_state.anchor_audio_dir = anchor
        app_state.zhuli_audio_dir = zhuli
        app_state.follow_audio_dir = follow
        app_state.like_audio_dir = like

        # ✅ 解决“换目录后还是旧音频”：清掉已排队的关注/点赞（若能拿到 dispatcher）
        self._try_clear_follow_like_queue()

        confirm_dialog(
            self,
            "已保存并应用",
            "目录已写入 runtime_state.json。\n\n注意：已排队的旧关注/点赞音频已清空，后续触发将使用新目录。",
        )
        self._update_target_path()

    def _try_clear_follow_like_queue(self):
        # 尽量兼容各种引用位置：main.dispatcher / main.audio_dispatcher / app_state.audio_dispatcher
        main = self.ctx.get("main", None)
        candidates = [
            getattr(main, "dispatcher", None),
            getattr(main, "audio_dispatcher", None),
            getattr(app_state, "audio_dispatcher", None),
            getattr(app_state, "dispatcher", None),
        ]
        disp = None
        for c in candidates:
            if c is not None:
                disp = c
                break
        if disp is None:
            return

        try:
            if hasattr(disp, "follow_q"):
                disp.follow_q.clear()
            if hasattr(disp, "like_q"):
                disp.like_q.clear()
        except Exception:
            pass

    # ===================== 工具：作用目录 =====================

    def _get_target_dir(self) -> str:
        name = self.cmb_target.currentText()
        if name == "主播目录":
            return getattr(app_state, "anchor_audio_dir", str(AUDIO_BASE_DIR)) or str(AUDIO_BASE_DIR)
        if name == "助播目录":
            return getattr(app_state, "zhuli_audio_dir", str(ZHULI_AUDIO_DIR)) or str(ZHULI_AUDIO_DIR)
        if name == "关注目录":
            return getattr(app_state, "follow_audio_dir", str(other_gz_audio)) or str(other_gz_audio)
        if name == "点赞目录":
            return getattr(app_state, "like_audio_dir", str(other_dz_audio)) or str(other_dz_audio)
        return getattr(app_state, "anchor_audio_dir", str(AUDIO_BASE_DIR)) or str(AUDIO_BASE_DIR)

    def _update_target_path(self):
        p = self._get_target_dir()
        self.lbl_target_path.setText(str(p))

    def _open_target_dir(self):
        p = self._get_target_dir()
        p = _ensure_dir(p) or p
        if not p or not os.path.isdir(p):
            confirm_dialog(self, "错误", f"目录不存在：\n{p}")
            return
        os.startfile(p)

    # ===================== handlers =====================

    def handle_reorder_audio(self):
        base_dir = self._get_target_dir()
        base_dir = _ensure_dir(base_dir) or base_dir
        if not base_dir or not os.path.isdir(base_dir):
            confirm_dialog(self, "错误", f"目录不存在：\n{base_dir}")
            return

        try:
            if not confirm_dialog(self, "确认操作", f"将对目录进行统一补号排序：\n{base_dir}\n\n确定继续？"):
                return
            renamed = reorder_audio_files(base_dir, SUPPORTED_AUDIO_EXTS)
            confirm_dialog(self, "完成", f"已重命名 {renamed} 个文件\n\n目录：\n{base_dir}")
        except Exception as e:
            confirm_dialog(self, "失败", str(e))

    def handle_copy_audio(self):
        base_dir = self._get_target_dir()
        base_dir = _ensure_dir(base_dir) or base_dir
        if not base_dir or not os.path.isdir(base_dir):
            confirm_dialog(self, "错误", f"目录不存在：\n{base_dir}")
            return

        # ✅ 不再输入名字：直接选文件
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择要复制的音频文件", base_dir, _audio_filter()
        )
        if not file_path:
            return
        if not os.path.isfile(file_path) or (not _is_audio_file(file_path)):
            confirm_dialog(self, "错误", "请选择有效的音频文件。")
            return

        count, ok = int_input_dialog(
            self, "复制数量", "请输入需要复制的份数：", value=10, min_value=1, max_value=9999
        )
        if not ok:
            return

        base_no_ext = os.path.splitext(os.path.basename(file_path))[0]
        suffix = os.path.splitext(os.path.basename(file_path))[1].lower()

        m = re.match(r"^(.*?)(\d+)$", base_no_ext)
        if not m:
            confirm_dialog(self, "文件名格式不正确", "被复制的音频文件名必须以数字结尾，例如：烟管165、讲解03")
            return

        prefix = m.group(1)
        num_str = m.group(2)
        width = len(num_str)

        # 扫描目标目录中已存在的同前缀同后缀序号
        pat = re.compile(rf"^{re.escape(prefix)}(\d+){re.escape(suffix)}$", re.IGNORECASE)
        nums = []
        try:
            for fn in os.listdir(base_dir):
                mm = pat.match(fn)
                if mm:
                    nums.append(int(mm.group(1)))
        except Exception:
            nums = []

        start_index = (max(nums) + 1) if nums else (int(num_str) + 1)

        # 复制：确保“真正生成 count 份”（遇到重名就跳过继续找下一个）
        created = 0
        n = start_index
        # 预估位数：终点位数可能更长
        width = max(width, len(str(start_index + count + 50)))

        first_n = None
        last_n = None

        while created < count:
            n_str = str(n).zfill(width)
            dst_name = f"{prefix}{n_str}{suffix}"
            dst_path = os.path.join(base_dir, dst_name)
            if os.path.exists(dst_path):
                n += 1
                continue

            try:
                shutil.copy2(file_path, dst_path)
            except Exception as e:
                confirm_dialog(self, "复制失败", str(e))
                return

            if first_n is None:
                first_n = n
            last_n = n

            created += 1
            n += 1

        confirm_dialog(
            self,
            "复制完成",
            f"源文件：{os.path.basename(file_path)}\n"
            f"已生成：{created} 份\n"
            f"序号范围：{first_n} ~ {last_n}\n\n"
            f"保存目录：\n{base_dir}",
        )

    def handle_split_audio(self):
        base_dir = self._get_target_dir()
        base_dir = _ensure_dir(base_dir) or base_dir
        if not base_dir or not os.path.isdir(base_dir):
            confirm_dialog(self, "错误", f"目录不存在：\n{base_dir}")
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择需要裁剪的音频", base_dir, _audio_filter()
        )
        if not file_path:
            return

        max_sec, ok = int_input_dialog(
            self,
            "设置最长时长（秒）",
            "请输入每段最长秒数（范围 5~300 秒）：",
            value=60,
            min_value=5,
            max_value=300,
            step=1,
        )
        if not ok:
            return

        try:
            files = smart_split_audio_to_dir(
                input_file=file_path,
                output_dir=base_dir,
                min_len=5,
                max_len=max_sec,
                prefix="讲解",
            )
            confirm_dialog(self, "裁剪完成", f"已生成 {len(files)} 段音频\n\n保存目录：\n{base_dir}")
        except Exception as e:
            confirm_dialog(self, "裁剪失败", str(e))
