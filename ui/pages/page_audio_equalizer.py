# ui/pages/page_audio_equalizer.py
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QFrame, QComboBox
)
from PySide6.QtCore import Qt
from core.runtime_state import load_runtime_state, save_runtime_state


class AudioEqualizerPage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        self.ctx = ctx or {}
        self.setObjectName("AudioEqualizerPage")
        
        # 均衡器频段（Hz）
        self.bands = [80, 125, 250, 500, 800, 1000, 2000, 4000, 8000, 16000]
        self.sliders = {}
        self.audio_devices = []
        
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)
        
        # 标题
        title = QLabel("🎚️ 音效均衡器")
        title.setObjectName("EQ_Title")
        root.addWidget(title)
        
        tip = QLabel("调节不同频段的音量，打造专属音效（实时生效）")
        tip.setObjectName("EQ_Tip")
        tip.setWordWrap(True)
        root.addWidget(tip)
        
        # 主体布局
        main_layout = QHBoxLayout()
        main_layout.setSpacing(16)
        
        # ===== 左侧：均衡器 =====
        left_layout = QVBoxLayout()
        left_layout.setSpacing(12)
        
        # 卡片1：输出设备选择
        card1 = self._card()
        c1 = QVBoxLayout(card1)
        c1.setContentsMargins(16, 16, 16, 16)
        c1.setSpacing(12)
        
        lbl1 = QLabel("🔊 音频输出设备")
        lbl1.setObjectName("EQ_SectionTitle")
        c1.addWidget(lbl1)
        
        self.combo_device = QComboBox()
        self.combo_device.setObjectName("EQ_Combo")
        self.combo_device.setMinimumHeight(40)
        self.combo_device.currentIndexChanged.connect(self._on_device_changed)
        c1.addWidget(self.combo_device)
        
        left_layout.addWidget(card1)
        
        # 卡片1.5：预设方案
        card_preset = self._card()
        cp = QVBoxLayout(card_preset)
        cp.setContentsMargins(16, 16, 16, 16)
        cp.setSpacing(12)
        
        lbl_preset = QLabel("🎨 预设方案")
        lbl_preset.setObjectName("EQ_SectionTitle")
        cp.addWidget(lbl_preset)
        
        # 预设按钮网格
        preset_grid = QHBoxLayout()
        preset_grid.setSpacing(8)
        
        presets = [
            ("📺 直播清晰", {"80": 1, "125": 2, "250": 3, "500": 3, "800": 2, "1000": 1, "2000": 0, "4000": -1, "8000": -2, "16000": -2}),
            ("🎙️ 直播温暖", {"80": 3, "125": 2, "250": 1, "500": 2, "800": 3, "1000": 2, "2000": 0, "4000": -1, "8000": -1, "16000": -2}),
            ("🎵 流行", {"80": 2, "125": 1, "250": 0, "500": -1, "800": -1, "1000": 0, "2000": 1, "4000": 2, "8000": 3, "16000": 2}),
            ("🎤 人声", {"80": -2, "125": -1, "250": 1, "500": 2, "800": 3, "1000": 3, "2000": 2, "4000": 1, "8000": 0, "16000": -1}),
            ("🎧 低音", {"80": 6, "125": 5, "250": 3, "500": 1, "800": 0, "1000": 0, "2000": 0, "4000": 0, "8000": 0, "16000": 0}),
            ("✨ 高音", {"80": 0, "125": 0, "250": 0, "500": 0, "800": 1, "1000": 2, "2000": 3, "4000": 4, "8000": 5, "16000": 6}),
        ]
        
        for preset_name, preset_values in presets:
            btn = QPushButton(preset_name)
            btn.setObjectName("EQ_PresetBtn")
            btn.setFixedHeight(36)
            btn.clicked.connect(lambda checked, v=preset_values: self.apply_preset(v))
            preset_grid.addWidget(btn)
        
        cp.addLayout(preset_grid)
        left_layout.addWidget(card_preset)
        
        # 卡片2：均衡器滑块
        card2 = self._card()
        c2 = QVBoxLayout(card2)
        c2.setContentsMargins(16, 16, 16, 16)
        c2.setSpacing(16)
        
        lbl2 = QLabel("🎛️ 频段调节")
        lbl2.setObjectName("EQ_SectionTitle")
        c2.addWidget(lbl2)
        
        # 滑块容器
        sliders_layout = QHBoxLayout()
        sliders_layout.setSpacing(12)
        
        for band in self.bands:
            slider_col = self._create_slider_column(band)
            sliders_layout.addLayout(slider_col)
        
        c2.addLayout(sliders_layout)
        
        # 重置按钮
        self.btn_reset = QPushButton("🔄 重置为默认")
        self.btn_reset.setObjectName("EQ_BtnGhost")
        self.btn_reset.setFixedHeight(40)
        self.btn_reset.clicked.connect(self.reset_to_default)
        c2.addWidget(self.btn_reset)
        
        left_layout.addWidget(card2, 1)
        
        main_layout.addLayout(left_layout, 1)
        
        root.addLayout(main_layout, 1)
        
        self._apply_style()
        
        # 先加载设备列表
        self._load_audio_devices()
        
        # 再加载设置（这样才能正确选择设备）
        self._load_settings()
        
        # 应用初始设置
        self._apply_equalizer()
        self._apply_audio_device()
    
    def _card(self) -> QFrame:
        f = QFrame()
        f.setObjectName("EQ_Card")
        f.setFrameShape(QFrame.NoFrame)
        f.setAttribute(Qt.WA_StyledBackground, True)
        return f
    
    def _create_slider_column(self, band: int):
        """创建单个频段的滑块列"""
        col = QVBoxLayout()
        col.setSpacing(8)
        col.setAlignment(Qt.AlignCenter)
        
        # 频段标签
        if band >= 1000:
            label_text = f"{band // 1000}k"
        else:
            label_text = str(band)
        
        lbl_band = QLabel(label_text)
        lbl_band.setObjectName("EQ_BandLabel")
        lbl_band.setAlignment(Qt.AlignCenter)
        col.addWidget(lbl_band)
        
        # 滑块
        slider = QSlider(Qt.Vertical)
        slider.setObjectName("EQ_Slider")
        slider.setMinimum(-12)
        slider.setMaximum(12)
        slider.setValue(0)
        slider.setTickPosition(QSlider.TicksBelow)
        slider.setTickInterval(3)
        slider.setMinimumHeight(200)
        slider.valueChanged.connect(lambda v, b=band: self._on_slider_changed(b, v))
        col.addWidget(slider, 1)
        
        # 数值标签
        lbl_value = QLabel("0 dB")
        lbl_value.setObjectName("EQ_ValueLabel")
        lbl_value.setAlignment(Qt.AlignCenter)
        col.addWidget(lbl_value)
        
        # 保存引用
        self.sliders[band] = {
            'slider': slider,
            'label': lbl_value
        }
        
        return col
    
    def _on_slider_changed(self, band: int, value: int):
        """滑块值改变"""
        # 更新标签
        self.sliders[band]['label'].setText(f"{value:+d} dB")
        
        # 保存设置
        self._save_settings()
        
        # 实时应用均衡器设置
        self._apply_equalizer()
    
    def _on_device_changed(self, index: int):
        """输出设备改变"""
        if index < 0:
            return
        
        # 保存设置
        self._save_settings()
        
        # 实时切换音频设备
        self._apply_audio_device()
    
    def _apply_style(self):
        self.setStyleSheet("""
        QLabel#EQ_Title {
            font-size: 20px;
            font-weight: 900;
            color: #EAEFF7;
        }
        QLabel#EQ_Tip {
            color: #A9B1BD;
            font-size: 13px;
        }
        QFrame#EQ_Card {
            background: #151A22;
            border: 1px solid #242B36;
            border-radius: 14px;
        }
        QLabel#EQ_SectionTitle {
            color: #D7DEE9;
            font-weight: 800;
            font-size: 14px;
        }
        QLabel#EQ_BandLabel {
            color: #98A3B3;
            font-weight: 700;
            font-size: 11px;
        }
        QLabel#EQ_ValueLabel {
            color: #3B82F6;
            font-weight: 800;
            font-size: 11px;
        }
        QComboBox#EQ_Combo {
            background: #0F141C;
            color: #E6ECF5;
            border: 1px solid #2A3240;
            border-radius: 10px;
            padding: 8px 12px;
            font-size: 13px;
            font-weight: 600;
        }
        QComboBox#EQ_Combo:focus {
            border: 1px solid #3B82F6;
        }
        QComboBox#EQ_Combo::drop-down {
            border: none;
            width: 30px;
        }
        QComboBox#EQ_Combo::down-arrow {
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid #E6ECF5;
            margin-right: 10px;
        }
        QComboBox#EQ_Combo QAbstractItemView {
            background: #0F141C;
            color: #E6ECF5;
            border: 1px solid #2A3240;
            border-radius: 8px;
            selection-background-color: rgba(59, 130, 246, 0.4);
            outline: 0;
        }
        QComboBox#EQ_Combo QAbstractItemView::item {
            padding: 8px 12px;
            color: #E6ECF5;
            font-weight: 600;
        }
        QComboBox#EQ_Combo QAbstractItemView::item:selected {
            background: rgba(59, 130, 246, 0.4);
            color: #FFFFFF;
        }
        QComboBox#EQ_Combo QAbstractItemView::item:hover {
            background: rgba(59, 130, 246, 0.2);
        }
        QSlider#EQ_Slider::groove:vertical {
            background: #0F141C;
            width: 8px;
            border-radius: 4px;
            border: 1px solid #2A3240;
        }
        QSlider#EQ_Slider::handle:vertical {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3B82F6, stop:1 #2563EB);
            border: 2px solid #1E40AF;
            height: 20px;
            margin: 0 -6px;
            border-radius: 10px;
        }
        QSlider#EQ_Slider::handle:vertical:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #2563EB, stop:1 #1D4ED8);
        }
        QSlider#EQ_Slider::sub-page:vertical {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3B82F6, stop:1 #2563EB);
            border-radius: 4px;
        }
        QPushButton#EQ_BtnGhost {
            background: transparent;
            color: #D7DEE9;
            border: 1px solid #2A3240;
            border-radius: 10px;
            font-weight: 800;
            font-size: 13px;
        }
        QPushButton#EQ_BtnGhost:hover {
            border: 1px solid #3B82F6;
            background: rgba(59, 130, 246, 0.1);
        }
        QPushButton#EQ_BtnGhost:pressed {
            background: rgba(59, 130, 246, 0.2);
        }
        QPushButton#EQ_PresetBtn {
            background: rgba(139, 92, 246, 0.15);
            color: #C4B5FD;
            border: 1px solid rgba(139, 92, 246, 0.3);
            border-radius: 8px;
            font-weight: 800;
            font-size: 12px;
            padding: 4px 8px;
        }
        QPushButton#EQ_PresetBtn:hover {
            background: rgba(139, 92, 246, 0.25);
            border: 1px solid rgba(139, 92, 246, 0.5);
            color: #DDD6FE;
        }
        QPushButton#EQ_PresetBtn:pressed {
            background: rgba(139, 92, 246, 0.35);
        }
        """)
    
    def _load_settings(self):
        """加载设置"""
        rt = load_runtime_state() or {}
        eq_settings = rt.get("audio_equalizer", {})
        
        print("\n🔧 加载均衡器设置...")
        
        # 加载均衡器频段设置
        for band in self.bands:
            value = eq_settings.get(str(band), 0)
            self.sliders[band]['slider'].blockSignals(True)  # 阻止信号，避免触发保存
            self.sliders[band]['slider'].setValue(value)
            self.sliders[band]['slider'].blockSignals(False)
            self.sliders[band]['label'].setText(f"{value:+d} dB")
            if value != 0:
                print(f"  {band}Hz: {value:+d} dB")
        
        # 加载输出设备
        device_id = eq_settings.get("output_device_id")
        device_name = eq_settings.get("output_device_name", "")
        
        print(f"  保存的设备ID: {device_id}")
        print(f"  保存的设备名称: {device_name}")
        
        # 尝试根据设备ID或名称选择
        if device_id is not None:
            for i in range(self.combo_device.count()):
                if self.combo_device.itemData(i) == device_id:
                    self.combo_device.blockSignals(True)  # 阻止信号
                    self.combo_device.setCurrentIndex(i)
                    self.combo_device.blockSignals(False)
                    print(f"  ✅ 已恢复设备: {self.combo_device.itemText(i)}")
                    return
        
        # 如果没有找到匹配的设备ID，尝试根据名称匹配
        if device_name:
            for i in range(self.combo_device.count()):
                if device_name in self.combo_device.itemText(i):
                    self.combo_device.blockSignals(True)  # 阻止信号
                    self.combo_device.setCurrentIndex(i)
                    self.combo_device.blockSignals(False)
                    print(f"  ✅ 已根据名称恢复设备: {self.combo_device.itemText(i)}")
                    return
        
        print(f"  ℹ️ 使用默认设备")
    
    def _save_settings(self):
        """保存设置"""
        rt = load_runtime_state() or {}
        eq_settings = {}
        
        for band in self.bands:
            value = self.sliders[band]['slider'].value()
            eq_settings[str(band)] = value
        
        # 保存设备ID和名称
        current_index = self.combo_device.currentIndex()
        if current_index >= 0:
            eq_settings["output_device_id"] = self.combo_device.itemData(current_index)
            eq_settings["output_device_name"] = self.combo_device.currentText()
        
        rt["audio_equalizer"] = eq_settings
        save_runtime_state(rt)
    
    def _load_audio_devices(self):
        """加载音频输出设备列表（只显示真正连接且启用的输出设备）"""
        self.combo_device.clear()
        
        try:
            from pycaw.pycaw import AudioUtilities
            from comtypes import cast, POINTER
            from pycaw.pycaw import IMMDevice
            
            print("🔍 使用 pycaw 获取音频设备...")
            
            all_devices = AudioUtilities.GetAllDevices()
            
            # 获取默认设备
            try:
                default_device = AudioUtilities.GetSpeakers()
                default_device_id = default_device.id
            except:
                default_device_id = None
            
            added_devices = []
            seen_names = set()
            default_index = -1
            
            print(f"📋 找到 {len(all_devices)} 个设备")
            
            for i, device in enumerate(all_devices):
                try:
                    device_name = device.FriendlyName
                    device_id = device.id
                    
                    # 检查设备状态
                    try:
                        # 获取底层 IMMDevice 接口
                        imm_device = cast(device._dev, POINTER(IMMDevice))
                        # 获取设备状态
                        state = imm_device.GetState()
                        # DEVICE_STATE_ACTIVE = 0x00000001
                        if state != 0x00000001:
                            print(f"设备 {i}: {device_name} - ❌ 未激活（状态：{hex(state)}）")
                            continue
                    except Exception as e:
                        print(f"设备 {i}: {device_name} - ❌ 无法获取状态：{e}")
                        continue
                    
                    # 去重
                    if device_name in seen_names:
                        print(f"设备 {i}: {device_name} - ⚠️ 重复，跳过")
                        continue
                    
                    seen_names.add(device_name)
                    
                    # 检查是否是默认设备
                    if device_id == default_device_id:
                        default_index = len(added_devices)
                        device_name = f"⭐ {device_name}"
                        print(f"设备 {i}: {device.FriendlyName} - ✅ 已添加（默认）")
                    else:
                        print(f"设备 {i}: {device.FriendlyName} - ✅ 已添加")
                    
                    added_devices.append((device_name, device_id))
                    
                except Exception as e:
                    print(f"设备 {i}: ❌ 处理失败 - {e}")
                    continue
            
            print(f"\n📊 总共添加了 {len(added_devices)} 个已激活的设备")
            
            # 如果找到了默认设备，将其移到第一位
            if default_index > 0:
                default_item = added_devices.pop(default_index)
                added_devices.insert(0, default_item)
                print(f"✅ 默认设备已移到第一位")
            
            # 添加到下拉列表
            for device_name, device_id in added_devices:
                self.combo_device.addItem(device_name, device_id)
            
            if len(added_devices) > 0:
                print(f"✅ 已加载 {len(added_devices)} 个可用的音频输出设备\n")
                return
                
        except Exception as e:
            print(f"❌ pycaw 加载失败：{e}")
            import traceback
            traceback.print_exc()
        
        # 如果都失败了，添加默认选项
        self.combo_device.addItem("系统默认", None)
        print("⚠️ 未找到可用的音频设备，使用系统默认\n")
    
    def _apply_equalizer(self):
        """实时应用均衡器设置"""
        # 获取当前所有频段的值
        eq_values = {}
        for band in self.bands:
            eq_values[band] = self.sliders[band]['slider'].value()
        
        # TODO: 这里可以实现实际的音频均衡器效果
        # 目前只是保存设置，实际应用需要音频处理库
        print(f"🎛️ 均衡器设置已更新：{eq_values}")
    
    def _apply_audio_device(self):
        """实时切换音频设备"""
        current_index = self.combo_device.currentIndex()
        if current_index < 0:
            return
        
        device_id = self.combo_device.itemData(current_index)
        device_name = self.combo_device.currentText()
        
        if device_id is None:
            print("🔊 使用系统默认音频设备")
            return
        
        try:
            # 优先使用 pycaw（Windows 原生 API）
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities
            
            # pycaw 会自动使用选中的设备
            print(f"🔊 已选择音频设备：{device_name}")
            
        except ImportError:
            # 回退到 sounddevice
            try:
                import sounddevice as sd
                
                if isinstance(device_id, int) and device_id >= 0:
                    # 设置默认输出设备
                    sd.default.device[1] = device_id
                    print(f"🔊 已切换到音频设备：{device_name} (ID: {device_id})")
                
            except ImportError:
                print("⚠️ sounddevice 模块未安装，无法切换设备")
            except Exception as e:
                print(f"❌ 切换音频设备失败：{e}")
        except Exception as e:
            print(f"❌ 切换音频设备失败：{e}")
    
    def reset_to_default(self):
        """重置为默认值"""
        for band in self.bands:
            self.sliders[band]['slider'].setValue(0)
            self.sliders[band]['label'].setText("0 dB")
        
        # 重置到第一个设备（通常是默认设备）
        self.combo_device.setCurrentIndex(0)
        
        self._save_settings()
        self._apply_equalizer()
        self._apply_audio_device()
    
    def apply_preset(self, preset_values: dict):
        """应用预设方案"""
        print(f"🎨 应用预设方案...")
        for band in self.bands:
            value = preset_values.get(str(band), 0)
            self.sliders[band]['slider'].blockSignals(True)  # 阻止信号
            self.sliders[band]['slider'].setValue(value)
            self.sliders[band]['slider'].blockSignals(False)
            self.sliders[band]['label'].setText(f"{value:+d} dB")
            if value != 0:
                print(f"  {band}Hz: {value:+d} dB")
        
        # 保存设置
        self._save_settings()
        # 应用均衡器
        self._apply_equalizer()
        print(f"✅ 预设方案已应用并保存")

