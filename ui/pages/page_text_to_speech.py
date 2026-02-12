# ui/pages/page_text_to_speech.py
import os
import time
import re
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QComboBox, QFrame, QFileDialog, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices

from api.voice_api import VoiceApiClient
from audio.voice_reporter import call_cloud_tts
from config import BASE_URL
from core.runtime_state import load_runtime_state, save_runtime_state
from core.state import app_state
from ui.dialogs import confirm_dialog


class HistoryItemWidget(QWidget):
    """生成记录列表项小部件"""
    play_clicked = Signal(str)  # 播放信号，传递文件路径
    open_folder_clicked = Signal(str)  # 打开文件夹信号，传递文件路径
    
    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)
        
        # 播放按钮（放在最左侧）
        self.btn_play = QPushButton("▶️")
        self.btn_play.setObjectName("HistoryPlayBtn")
        self.btn_play.setFixedSize(40, 40)
        self.btn_play.setToolTip("播放")
        self.btn_play.setStyleSheet("""
            QPushButton#HistoryPlayBtn {
                background: rgba(59, 130, 246, 0.2);
                color: #3B82F6;
                border: 1px solid rgba(59, 130, 246, 0.4);
                border-radius: 8px;
                font-weight: 800;
                font-size: 18px;
                padding: 2px;
            }
            QPushButton#HistoryPlayBtn:hover {
                background: rgba(59, 130, 246, 0.3);
                border: 1px solid rgba(59, 130, 246, 0.6);
            }
            QPushButton#HistoryPlayBtn:pressed {
                background: rgba(59, 130, 246, 0.4);
            }
        """)
        self.btn_play.clicked.connect(self._on_play_clicked)
        layout.addWidget(self.btn_play)
        
        # 打开文件夹按钮（第二个）
        self.btn_open = QPushButton("📂")
        self.btn_open.setObjectName("HistoryOpenBtn")
        self.btn_open.setFixedSize(40, 40)
        self.btn_open.setToolTip("打开文件所在位置")
        self.btn_open.setStyleSheet("""
            QPushButton#HistoryOpenBtn {
                background: rgba(34, 197, 94, 0.2);
                color: #22C55E;
                border: 1px solid rgba(34, 197, 94, 0.4);
                border-radius: 8px;
                font-weight: 800;
                font-size: 18px;
                padding: 2px;
            }
            QPushButton#HistoryOpenBtn:hover {
                background: rgba(34, 197, 94, 0.3);
                border: 1px solid rgba(34, 197, 94, 0.6);
            }
            QPushButton#HistoryOpenBtn:pressed {
                background: rgba(34, 197, 94, 0.4);
            }
        """)
        self.btn_open.clicked.connect(self._on_open_folder_clicked)
        layout.addWidget(self.btn_open)
        
        # 文件名标签（放在按钮右侧）
        filename = os.path.basename(file_path)
        self.lbl_name = QLabel(f"📄 {filename}")
        self.lbl_name.setObjectName("HistoryItemName")
        self.lbl_name.setStyleSheet("""
            QLabel#HistoryItemName {
                color: #D7DEE9;
                font-weight: 600;
                font-size: 12px;
            }
        """)
        layout.addWidget(self.lbl_name, 1)
    
    def _on_play_clicked(self):
        """播放按钮被点击"""
        self.play_clicked.emit(self.file_path)
    
    def _on_open_folder_clicked(self):
        """打开文件夹按钮被点击"""
        self.open_folder_clicked.emit(self.file_path)


class TTSWorker(QThread):
    """后台TTS工作线程"""
    progress = Signal(str)  # 进度信息
    finished = Signal(bool, str, str)  # success, file_path, error_msg
    
    def __init__(self, model_id: int, text: str, save_dir: str, filename: str):
        super().__init__()
        self.model_id = model_id
        self.text = text
        self.save_dir = save_dir
        self.filename = filename
    
    def run(self):
        try:
            self.progress.emit("正在生成语音...")
            
            # 调用报时的TTS接口
            temp_file = call_cloud_tts(self.text, self.model_id)
            
            # 移动到目标目录
            save_path = Path(self.save_dir) / self.filename
            save_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 复制文件
            import shutil
            shutil.copy(temp_file, save_path)
            
            self.progress.emit("语音生成完成！")
            self.finished.emit(True, str(save_path), "")
            
        except Exception as e:
            import traceback
            self.finished.emit(False, "", f"生成失败：{str(e)}\n\n{traceback.format_exc()}")


class TextToSpeechPage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        self.ctx = ctx or {}
        self.setObjectName("TextToSpeechPage")
        
        # 直接使用 app_state 的 license_key，而不是从 ctx 获取
        self.models = []
        self.tts_worker = None
        self.history = []  # 生成记录
        self.last_generated_file = None  # 最后生成的文件
        
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)
        
        # 标题
        title = QLabel("🎙️ 文本转语音")
        title.setObjectName("TTS_Title")
        root.addWidget(title)
        
        tip = QLabel("输入文本，选择音色模型，一键生成语音文件")
        tip.setObjectName("TTS_Tip")
        tip.setWordWrap(True)
        root.addWidget(tip)
        
        # 主体布局：左侧设置，右侧记录
        main_layout = QHBoxLayout()
        main_layout.setSpacing(16)
        
        # ===== 左侧：设置区域 =====
        left_layout = QVBoxLayout()
        left_layout.setSpacing(12)
        
        # 卡片1：音色选择
        card1 = self._card()
        c1 = QVBoxLayout(card1)
        c1.setContentsMargins(16, 16, 16, 16)
        c1.setSpacing(12)
        
        lbl1 = QLabel("选择音色模型")
        lbl1.setObjectName("TTS_SectionTitle")
        c1.addWidget(lbl1)
        
        model_row = QHBoxLayout()
        model_row.setSpacing(12)
        
        self.combo_model = QComboBox()
        self.combo_model.setObjectName("TTS_Combo")
        self.combo_model.setMinimumHeight(40)
        model_row.addWidget(self.combo_model, 1)
        
        self.btn_refresh = QPushButton("🔄")
        self.btn_refresh.setObjectName("TTS_BtnGhost")
        self.btn_refresh.setFixedSize(40, 40)
        self.btn_refresh.setToolTip("刷新音色列表")
        self.btn_refresh.clicked.connect(self.load_models)
        model_row.addWidget(self.btn_refresh)
        
        c1.addLayout(model_row)
        left_layout.addWidget(card1)
        
        # 卡片2：保存目录
        card2 = self._card()
        c2 = QVBoxLayout(card2)
        c2.setContentsMargins(16, 16, 16, 16)
        c2.setSpacing(12)
        
        lbl2 = QLabel("保存目录")
        lbl2.setObjectName("TTS_SectionTitle")
        c2.addWidget(lbl2)
        
        self.lbl_save_dir = QLabel("")
        self.lbl_save_dir.setObjectName("TTS_PathLabel")
        self.lbl_save_dir.setWordWrap(True)
        self.lbl_save_dir.setMinimumHeight(40)
        c2.addWidget(self.lbl_save_dir, 1)
        
        dir_btn_row = QHBoxLayout()
        dir_btn_row.setSpacing(10)
        
        self.btn_change_dir = QPushButton("📝 修改目录")
        self.btn_change_dir.setObjectName("TTS_BtnGhost")
        self.btn_change_dir.setFixedHeight(36)
        self.btn_change_dir.clicked.connect(self.change_save_dir)
        dir_btn_row.addWidget(self.btn_change_dir)
        
        self.btn_open_dir = QPushButton("📂 打开目录")
        self.btn_open_dir.setObjectName("TTS_BtnGhost")
        self.btn_open_dir.setFixedHeight(36)
        self.btn_open_dir.clicked.connect(self.open_save_dir)
        dir_btn_row.addWidget(self.btn_open_dir)
        
        c2.addLayout(dir_btn_row)
        left_layout.addWidget(card2)
        
        # 卡片3：文本输入
        card3 = self._card()
        c3 = QVBoxLayout(card3)
        c3.setContentsMargins(16, 16, 16, 16)
        c3.setSpacing(12)
        
        lbl3 = QLabel("输入文本内容")
        lbl3.setObjectName("TTS_SectionTitle")
        c3.addWidget(lbl3)
        
        self.text_input = QTextEdit()
        self.text_input.setObjectName("TTS_Text")
        self.text_input.setPlaceholderText("请输入要转换成语音的文本内容...\n\n支持中文、英文、数字等")
        self.text_input.setMinimumHeight(200)
        c3.addWidget(self.text_input, 1)
        
        left_layout.addWidget(card3, 1)
        
        # 状态提示
        self.status_label = QLabel("")
        self.status_label.setObjectName("TTS_Status")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setVisible(False)
        left_layout.addWidget(self.status_label)
        
        # 生成按钮
        self.btn_generate = QPushButton("🎵 生成语音")
        self.btn_generate.setObjectName("TTS_BtnPrimary")
        self.btn_generate.setFixedHeight(48)
        self.btn_generate.clicked.connect(self.generate_speech)
        left_layout.addWidget(self.btn_generate)
        
        # 播放按钮
        self.btn_play = QPushButton("▶️ 播放最后生成的语音")
        self.btn_play.setObjectName("TTS_BtnGhost")
        self.btn_play.setFixedHeight(40)
        self.btn_play.setEnabled(False)
        self.btn_play.clicked.connect(self.play_last_generated)
        left_layout.addWidget(self.btn_play)
        
        main_layout.addLayout(left_layout, 2)
        
        # ===== 右侧：生成记录 =====
        right_layout = QVBoxLayout()
        right_layout.setSpacing(12)
        
        card_history = self._card()
        ch = QVBoxLayout(card_history)
        ch.setContentsMargins(16, 16, 16, 16)
        ch.setSpacing(12)
        
        history_header = QHBoxLayout()
        lbl_history = QLabel("生成记录")
        lbl_history.setObjectName("TTS_SectionTitle")
        history_header.addWidget(lbl_history)
        history_header.addStretch(1)
        
        self.btn_clear_history = QPushButton("🗑️ 清空")
        self.btn_clear_history.setObjectName("TTS_BtnGhost")
        self.btn_clear_history.setFixedHeight(32)
        self.btn_clear_history.clicked.connect(self.clear_history)
        history_header.addWidget(self.btn_clear_history)
        
        ch.addLayout(history_header)
        
        self.history_list = QListWidget()
        self.history_list.setObjectName("TTS_HistoryList")
        self.history_list.itemDoubleClicked.connect(self.open_history_file)
        ch.addWidget(self.history_list, 1)
        
        right_layout.addWidget(card_history, 1)
        
        main_layout.addLayout(right_layout, 1)
        
        root.addLayout(main_layout, 1)
        
        self._apply_style()
        self._load_settings()
        self.load_models()
        self.load_history()
    
    def _card(self) -> QFrame:
        f = QFrame()
        f.setObjectName("TTS_Card")
        f.setFrameShape(QFrame.NoFrame)
        f.setAttribute(Qt.WA_StyledBackground, True)
        return f
    
    def _apply_style(self):
        self.setStyleSheet("""
        QLabel#TTS_Title {
            font-size: 20px;
            font-weight: 900;
            color: #EAEFF7;
        }
        QLabel#TTS_Tip {
            color: #A9B1BD;
            font-size: 13px;
        }
        QFrame#TTS_Card {
            background: #151A22;
            border: 1px solid #242B36;
            border-radius: 14px;
        }
        QLabel#TTS_SectionTitle {
            color: #D7DEE9;
            font-weight: 800;
            font-size: 14px;
        }
        QLabel#TTS_PathLabel {
            color: #98A3B3;
            font-size: 12px;
            padding: 8px;
            background: #0F141C;
            border-radius: 8px;
        }
        QComboBox#TTS_Combo {
            background: #0F141C;
            color: #E6ECF5;
            border: 1px solid #2A3240;
            border-radius: 10px;
            padding: 8px 12px;
            font-size: 13px;
            font-weight: 600;
        }
        QComboBox#TTS_Combo:focus {
            border: 1px solid #3B82F6;
        }
        QComboBox#TTS_Combo::drop-down {
            border: none;
            width: 30px;
        }
        QComboBox#TTS_Combo::down-arrow {
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid #E6ECF5;
            margin-right: 10px;
        }
        QComboBox#TTS_Combo QAbstractItemView {
            background: #0F141C;
            color: #E6ECF5;
            border: 1px solid #2A3240;
            border-radius: 8px;
            selection-background-color: rgba(59, 130, 246, 0.4);
            outline: 0;
        }
        QComboBox#TTS_Combo QAbstractItemView::item {
            padding: 8px 12px;
            color: #E6ECF5;
            font-weight: 600;
        }
        QComboBox#TTS_Combo QAbstractItemView::item:selected {
            background: rgba(59, 130, 246, 0.4);
            color: #FFFFFF;
        }
        QComboBox#TTS_Combo QAbstractItemView::item:hover {
            background: rgba(59, 130, 246, 0.2);
        }
        QTextEdit#TTS_Text {
            background: #0F141C;
            color: #E6ECF5;
            border: 1px solid #2A3240;
            border-radius: 12px;
            padding: 12px;
            font-size: 13px;
            selection-background-color: #3B82F6;
        }
        QTextEdit#TTS_Text:focus {
            border: 1px solid #3B82F6;
        }
        QListWidget#TTS_HistoryList {
            background: #0F141C;
            border: 1px solid #2A3240;
            border-radius: 10px;
            outline: 0;
        }
        QListWidget#TTS_HistoryList::item {
            padding: 10px;
            border-radius: 6px;
            color: #D7DEE9;
            font-weight: 600;
        }
        QListWidget#TTS_HistoryList::item:selected {
            background: rgba(59, 130, 246, 0.3);
            color: #FFFFFF;
        }
        QListWidget#TTS_HistoryList::item:hover {
            background: rgba(59, 130, 246, 0.2);
            color: #FFFFFF;
        }
        QLabel#TTS_Status {
            color: #A9B1BD;
            font-size: 13px;
            padding: 8px;
            background: #0F141C;
            border-radius: 8px;
        }
        QPushButton#TTS_BtnPrimary {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3B82F6, stop:1 #2563EB);
            color: white;
            border: none;
            border-radius: 12px;
            font-weight: 900;
            font-size: 14px;
        }
        QPushButton#TTS_BtnPrimary:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #2563EB, stop:1 #1D4ED8);
        }
        QPushButton#TTS_BtnPrimary:pressed {
            background: #1E40AF;
        }
        QPushButton#TTS_BtnPrimary:disabled {
            background: #6B7280;
            color: #D1D5DB;
        }
        QPushButton#TTS_BtnGhost {
            background: transparent;
            color: #D7DEE9;
            border: 1px solid #2A3240;
            border-radius: 10px;
            font-weight: 800;
            font-size: 13px;
        }
        QPushButton#TTS_BtnGhost:hover {
            border: 1px solid #3B82F6;
            background: rgba(59, 130, 246, 0.1);
        }
        QPushButton#TTS_BtnGhost:pressed {
            background: rgba(59, 130, 246, 0.2);
        }
        QPushButton#TTS_BtnGhost:disabled {
            background: transparent;
            color: #6B7280;
            border: 1px solid #4B5563;
        }
        """)
    
    def _load_settings(self):
        """加载设置"""
        rt = load_runtime_state() or {}
        save_dir = rt.get("tts_save_dir", "")
        
        if not save_dir:
            # 默认保存到桌面的TTS文件夹
            desktop = Path.home() / "Desktop" / "TTS语音"
            save_dir = str(desktop)
            rt["tts_save_dir"] = save_dir
            save_runtime_state(rt)
        
        self.save_dir = save_dir
        self.lbl_save_dir.setText(save_dir)
    
    def change_save_dir(self):
        """更改保存目录"""
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "选择保存目录",
            self.save_dir
        )
        
        if dir_path:
            self.save_dir = dir_path
            self.lbl_save_dir.setText(dir_path)
            
            # 保存设置
            rt = load_runtime_state() or {}
            rt["tts_save_dir"] = dir_path
            save_runtime_state(rt)
    
    def open_save_dir(self):
        """打开保存目录"""
        if os.path.exists(self.save_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.save_dir))
        else:
            confirm_dialog(self, "提示", "保存目录不存在")
    
    def load_models(self):
        """加载音色模型列表"""
        try:
            self.btn_refresh.setEnabled(False)
            self.combo_model.clear()
            self.combo_model.addItem("正在加载...")
            
            # 使用 app_state 的 license_key 和 machine_code
            client = VoiceApiClient(BASE_URL, app_state.license_key)
            client.machine_code = app_state.machine_code
            resp = client.list_models()
            if not isinstance(resp, dict) or resp.get("code") != 0:
                confirm_dialog(self, "加载失败", f"无法获取音色列表：\n{resp}")
                self.combo_model.clear()
                self.combo_model.addItem("加载失败")
                return
            
            self.models = resp.get("data", []) or []
            self.combo_model.clear()
            
            if not self.models:
                self.combo_model.addItem("暂无音色模型，请先上传")
                return
            
            for model in self.models:
                name = model.get("name", "未命名")
                model_id = model.get("id")
                is_default = model.get("is_default", False)
                
                display_name = f"{'⭐ ' if is_default else ''}{name}"
                self.combo_model.addItem(display_name, model_id)
            
        except Exception as e:
            confirm_dialog(self, "加载失败", f"加载音色模型失败：\n{str(e)}")
            self.combo_model.clear()
            self.combo_model.addItem("加载失败")
        finally:
            self.btn_refresh.setEnabled(True)
    
    def generate_speech(self):
        """生成语音"""
        text = self.text_input.toPlainText().strip()
        if not text:
            confirm_dialog(self, "提示", "请输入要转换的文本内容")
            return
        
        if self.combo_model.count() == 0 or not self.combo_model.currentData():
            confirm_dialog(self, "提示", "请先选择音色模型")
            return
        
        model_id = self.combo_model.currentData()
        
        # 生成文件名：文本前10字
        text_preview = re.sub(r'[\\/:*?"<>|]', '', text[:10])  # 移除非法字符，取前10个字
        if not text_preview:
            text_preview = "语音"
        
        # 如果文件已存在，添加数字后缀
        base_filename = text_preview
        counter = 1
        filename = f"{base_filename}.wav"
        save_path = Path(self.save_dir) / filename
        
        while save_path.exists():
            filename = f"{base_filename}_{counter}.wav"
            save_path = Path(self.save_dir) / filename
            counter += 1
        
        # 禁用按钮
        self.btn_generate.setEnabled(False)
        self.status_label.setVisible(True)
        self.status_label.setText("⏳ 正在生成语音...")
        
        # 创建工作线程
        self.tts_worker = TTSWorker(model_id, text, self.save_dir, filename)
        self.tts_worker.progress.connect(self._on_tts_progress)
        self.tts_worker.finished.connect(self._on_tts_finished)
        self.tts_worker.start()
    
    def _on_tts_progress(self, message: str):
        """TTS进度更新"""
        self.status_label.setText(f"⏳ {message}")
    
    def _on_tts_finished(self, success: bool, file_path: str, error_msg: str):
        """TTS完成"""
        self.btn_generate.setEnabled(True)
        
        if success:
            self.status_label.setText(f"✅ 语音已保存：{os.path.basename(file_path)}")
            self.last_generated_file = file_path
            self.btn_play.setEnabled(True)  # 启用播放按钮
            
            # 添加到记录
            self.add_history(file_path)
            
            # 提示
            confirm_dialog(self, "生成成功", f"语音文件已保存到：\n{file_path}")
        else:
            self.status_label.setText(f"❌ 生成失败")
            self.last_generated_file = None
            self.btn_play.setEnabled(False)  # 禁用播放按钮
            confirm_dialog(self, "生成失败", error_msg)
    
    def add_history(self, file_path: str):
        """添加到生成记录"""
        self.history.insert(0, file_path)
        
        # 只保留最近50条
        if len(self.history) > 50:
            self.history = self.history[:50]
        
        # 保存到配置
        rt = load_runtime_state() or {}
        rt["tts_history"] = self.history
        save_runtime_state(rt)
        
        # 刷新列表
        self.load_history()
    
    def load_history(self):
        """加载生成记录"""
        rt = load_runtime_state() or {}
        self.history = rt.get("tts_history", []) or []
        
        self.history_list.clear()
        
        for file_path in self.history:
            if os.path.exists(file_path):
                item = QListWidgetItem()
                item.setData(Qt.UserRole, file_path)
                
                # 创建自定义小部件
                widget = HistoryItemWidget(file_path)
                widget.play_clicked.connect(self.play_audio_file)
                widget.open_folder_clicked.connect(self.open_file_location)
                
                item.setSizeHint(widget.sizeHint())
                self.history_list.addItem(item)
                self.history_list.setItemWidget(item, widget)
    
    def open_history_file(self, item: QListWidgetItem):
        """打开历史文件所在位置"""
        file_path = item.data(Qt.UserRole)
        if file_path and os.path.exists(file_path):
            # 打开文件所在文件夹并选中文件
            import subprocess
            subprocess.run(['explorer', '/select,', file_path])
    
    def clear_history(self):
        """清空记录"""
        if not confirm_dialog(self, "确认清空", "确定要清空所有生成记录吗？\n（不会删除文件，只清空记录列表）"):
            return
        
        self.history = []
        rt = load_runtime_state() or {}
        rt["tts_history"] = []
        save_runtime_state(rt)
        
        self.load_history()
    
    def play_last_generated(self):
        """播放最后生成的语音"""
        if not self.last_generated_file or not os.path.exists(self.last_generated_file):
            confirm_dialog(self, "提示", "没有可播放的语音文件")
            return
        
        self.play_audio_file(self.last_generated_file)
    
    def play_audio_file(self, file_path: str):
        """播放音频文件"""
        if not file_path or not os.path.exists(file_path):
            confirm_dialog(self, "提示", "文件不存在或已被删除")
            return
        
        try:
            import subprocess
            import sys
            # 使用 winsound 模块播放（Windows 内置）
            if sys.platform == 'win32':
                import winsound
                winsound.PlaySound(file_path, winsound.SND_FILENAME)
            else:
                confirm_dialog(self, "提示", "当前系统不支持播放")
        except Exception as e:
            confirm_dialog(self, "播放失败", f"无法播放语音文件：\n{str(e)}")
    
    def open_file_location(self, file_path: str):
        """打开文件所在位置"""
        if not file_path or not os.path.exists(file_path):
            confirm_dialog(self, "提示", "文件不存在或已被删除")
            return
        
        try:
            import subprocess
            subprocess.run(['explorer', '/select,', file_path])
        except Exception as e:
            confirm_dialog(self, "打开失败", f"无法打开文件位置：\n{str(e)}")
    
    def _on_play_finished(self):
        """播放完成"""
        self.btn_play.setEnabled(True)
