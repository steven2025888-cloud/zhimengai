# config.py
import os
from pathlib import Path
import sys

BASE_URL = "https://api.zhimengai.xyz"

# ================== WS 配置 ==================
WS_URL = "wss://api.zhimengai.xyz/live"

# ================== Playwright & 微信视频号 ==================
LOGIN_URL = "https://channels.weixin.qq.com/login.html"
LIVE_URL_PREFIX = "https://channels.weixin.qq.com/platform/live/liveBuild"
TARGET_API_KEYWORD = "mmfinderassistant-bin/live/msg"





BASE_DIR = Path(__file__).resolve().parent
USER_DATA_DIR = Path.home() / ".ai_live_tool"
USER_DATA_DIR.mkdir(exist_ok=True)

STATE_FILE = str((USER_DATA_DIR / "wx_login_state.json").resolve())


HOME_URL = "https://channels.weixin.qq.com/platform/live/home"


# config.py
DOUYIN_PROFILE_DIR = "./profiles/douyin"   # 每个用户可再细分
DOUYIN_LOGIN_URL = "https://buyin.jinritemai.com/mpa/account/login"
DOUYIN_DASHBOARD_URL = "https://buyin.jinritemai.com/dashboard/live/control"
DOUYIN_API_KEYWORD = "/api/anchor/comment/info"
DOUYIN_STATE_FILE = "douyin_state.json"



# ================== 音频资源 ==================
def get_app_dir():
    # 打包后：exe所在目录
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    # 开发环境：当前运行目录
    return Path.cwd()

BASE_DIR = get_app_dir()
AUDIO_BASE_DIR = BASE_DIR / "audio_assets"


SUPPORTED_AUDIO_EXTS = (".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg")

# 前缀约定：讲解* / 尺寸*
PREFIX_RANDOM = "讲解"
PREFIX_SIZE = "尺寸"

# 关键词触发（可扩展：价格/发货/材质…）
KEYWORD_SIZE = "尺寸"

# 随机讲解投递间隔（秒）
RANDOM_PUSH_INTERVAL = 0.8

# 主循环 tick 间隔
MAIN_TICK_INTERVAL = 0.25






