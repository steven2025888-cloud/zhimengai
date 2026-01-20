import sys
from pathlib import Path

# ================== 基础配置 ==================
zhandian = "api.zhimengai.xyz"
BASE_URL = "https://" + zhandian
UPDATE_API = BASE_URL + "/api/update/check"
CURRENT_VERSION = "1.0.4"

WS_URL = "wss://" + zhandian + "/live"


# ================== 运行根目录（exe 同级） ==================
def get_app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

BASE_DIR = get_app_dir()


# ================== 登录缓存（永久保存） ==================
STATE_FILE = BASE_DIR / "wx_login_state.json"
DOUYIN_STATE_FILE = BASE_DIR / "douyin_login_state.json"


# ================== 微信视频号 ==================
LOGIN_URL = "https://channels.weixin.qq.com/login.html"
HOME_URL = "https://channels.weixin.qq.com/platform/live/home"
LIVE_URL_PREFIX = "https://channels.weixin.qq.com/platform/live/liveBuild"
TARGET_API_KEYWORD = "mmfinderassistant-bin/live/msg"


# ================== 抖音 ==================
DOUYIN_LOGIN_URL = "https://buyin.jinritemai.com/mpa/account/login"
DOUYIN_DASHBOARD_URL = "https://buyin.jinritemai.com/mpa/account/login"

# DOUYIN_DASHBOARD_URL = "https://buyin.jinritemai.com/dashboard/live/control"
DOUYIN_API_KEYWORD = "/api/anchor/comment/info"


# ================== 音频资源目录 ==================
AUDIO_BASE_DIR = BASE_DIR / "zhubo_audio"
AUDIO_BASE_DIR.mkdir(parents=True, exist_ok=True)
# ================== 助播音频目录 ==================
ZHULI_AUDIO_DIR = BASE_DIR / "zhuli_audio"
ZHULI_AUDIO_DIR.mkdir(parents=True, exist_ok=True)


SUPPORTED_AUDIO_EXTS = (".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg")

PREFIX_RANDOM = "讲解"
PREFIX_SIZE = "尺寸"
KEYWORD_SIZE = "尺寸"

RANDOM_PUSH_INTERVAL = 0.8
MAIN_TICK_INTERVAL = 0.25
