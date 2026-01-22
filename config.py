import sys
from pathlib import Path



def app_dir() -> Path:
    # 打包后：exe 所在目录
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # 开发时：项目根目录（config.py 在根目录）
    return Path(__file__).resolve().parent

BASE_DIR = app_dir()
IMG_DIR = BASE_DIR / "img"
FFMPEG_DIR = BASE_DIR / "ffmpeg"
FFMPEG_EXE = FFMPEG_DIR / "ffmpeg.exe"

# ================== 基础配置 ==================
zhandian = "api.zhimengai.xyz"
BASE_URL = "https://" + zhandian
UPDATE_API = BASE_URL + "/api/update/check"
CURRENT_VERSION = "1.0.5"

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

# ================== 关注音频目录 ==================
other_gz_audio = BASE_DIR / "other_audio/关注"
other_gz_audio.mkdir(parents=True, exist_ok=True)

# ================== 点赞音频目录 ==================
other_dz_audio = BASE_DIR / "other_audio/点赞"
other_dz_audio.mkdir(parents=True, exist_ok=True)


# ================== 关键词目录 ==================
KEYWORDS_BASE_DIR = BASE_DIR / "keywords_audio"
KEYWORDS_BASE_DIR.mkdir(parents=True, exist_ok=True)


SUPPORTED_AUDIO_EXTS = (".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg")


# 说明文档（可改成你的真实文档地址）
DOC_URL = "https://share.note.youdao.com/s/Ae6RJS7k"
# 关键词规则说明（问号按钮跳转）
KEYWORD_RULE_URL = "https://share.note.youdao.com/s/BYVl9xov"


ZHULI_HELP_URL = "https://share.note.youdao.com/s/BYVl9xov"

# AI Key 注册/购买页面
AI_KEY_REGISTER_URL = "https://ai.zhimengai.xyz/console/token"

# AI回复说明文档
AI_REPLY_HELP_URL = "https://你的AI回复说明文档"


AI_REPLY_MODELS = [
    {"label": "DeepSeek", "id": "deepseek-chat",   "icon": r"img\Deepseek.svg"},
    {"label": "豆包",     "id": "deepseek-chat", "icon": r"img\doubao.png"},
    {"label": "GPT5.2",         "id": "gpt-4.1-mini","icon": r"img\openai.svg"},
]
