
project/
│
├── main.py                 ⭐ 程序入口（原 hudie_caiji）
│
├── core/
│   ├── live_listener.py    🎥 Playwright + 弹幕解析
│   ├── ws_client.py        🌐 WebSocket 发送
│   └── state.py            🧠 全局状态（PlayMode / flags）
│
├── audio/
│   ├── audio_player.py     🔊 纯播放（只干一件事）
│   ├── audio_dispatcher.py 🎼 音频调度器（队列 + 优先级）
│   └── audio_picker.py     🎲 讲解* / 尺寸* 选音频
│
├── tts/
│   └── index_tts.py        🗣️ IndexTTS
│
└── config.py               ⚙️ 常量配置
