import os
import time
import json
import base64
from typing import Any, Dict
from playwright.sync_api import sync_playwright, Response, Page
import asyncio
import threading
import websockets
import subprocess
import random
import datetime

import audio_player as audio_player
import index_tts_play as ttsplay
from zoneinfo import ZoneInfo  # Python 3.9+
import AudioManager as am
from enum import Enum
import queue



audio_cmd_q = queue.Queue()

class PlayMode(Enum):
    RANDOM = 1      # 随机讲解
    SIZE = 2        # 尺寸回复

# 主线程播放状态
current_playing = False

# ================== WS 配置 ==================
WS_URL = "wss://api.zhimengai.xyz/live"   # 👉 改成你的 WS 服务地址
ws_queue = asyncio.Queue()

# ================== 配置 ==================
LOGIN_URL = "https://channels.weixin.qq.com/login.html"
LIVE_URL_PREFIX = "https://channels.weixin.qq.com/platform/live/liveBuild"
TARGET_API_KEYWORD = "mmfinderassistant-bin/live/msg"
STATE_FILE = "../wx_channels_state.json"

# ================== 全局状态 ==================
is_listening = False
seen_seq = set()


audio_manager = am.AudioPlayerThread()
play_mode = PlayMode.RANDOM




def random_play_loop_cmd():
    while True:
        if play_mode != PlayMode.RANDOM:
            time.sleep(0.1)
            continue

        wav = random_pick_jiejie_audio()
        audio_cmd_q.put(("PLAY_RANDOM", wav))
        # 等主线程播完再投递下一首（用一个简单的节流）
        time.sleep(1.0)


def random_play_loop():
    """
    后台永久随机播放线程（只负责投递指令）
    """
    while True:
        if play_mode != PlayMode.RANDOM:
            time.sleep(0.1)
            continue

        wav = random_pick_jiejie_audio()

        # 只投递，不播放、不等待
        audio_cmd_q.put(("PLAY_RANDOM", wav))

        # 稍微 sleep，避免刷爆队列
        time.sleep(0.5)



def random_pick_size_audio():
    """
    随机选一个「尺寸*」音频
    """
    desktop = os.path.join(os.path.expanduser("~"), "Desktop", "yinpin")
    supported = (".mp3", ".wav", ".aac", ".m4a")

    files = [
        f for f in os.listdir(desktop)
        if f.startswith("尺寸") and f.lower().endswith(supported)
    ]

    if not files:
        raise RuntimeError("未找到任何「尺寸*」音频")

    return os.path.join(desktop, random.choice(files))


def handle_size_keyword():
    global play_mode

    print("📏 触发【尺寸】关键词")

    play_mode = PlayMode.SIZE

    # 立刻停掉随机播放
    audio_manager.stop()

    size_audio = random_pick_size_audio()

    def on_size_finished():
        global play_mode
        print("🔁 尺寸播放完，恢复随机讲解")
        play_mode = PlayMode.RANDOM

    audio_manager.play(size_audio, on_finished=on_size_finished)


def random_pick_jiejie_audio():
    """
    从桌面 yinpin 文件夹中，随机选一个「讲解*」音频文件
    支持 mp3 / wav / m4a / aac / flac / ogg
    返回完整文件路径
    """
    desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
    yinpin_dir = os.path.join(desktop_path, "yinpin")

    if not os.path.exists(yinpin_dir):
        raise FileNotFoundError(f"音频目录不存在: {yinpin_dir}")

    supported_exts = (".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg")

    audio_files = [
        f for f in os.listdir(yinpin_dir)
        if f.startswith("讲解") and f.lower().endswith(supported_exts)
    ]

    if not audio_files:
        raise RuntimeError("未找到任何「讲解*」音频文件")

    chosen_file = random.choice(audio_files)
    return os.path.join(yinpin_dir, chosen_file)



async def ws_sender():
    """
    WebSocket 客户端：
    - 自动重连
    - 发送数据
    - 接收并打印服务器消息
    """
    while True:
        try:
            print(f"🔌 正在连接 WS：{WS_URL}")
            async with websockets.connect(WS_URL, ping_interval=20) as ws:
                print("✅ WS 已连接")

                async def sender():
                    while True:
                        data = await ws_queue.get()
                        await ws.send(json.dumps(data, ensure_ascii=False))
                        print(f"📤 WS 已发送：{data}")

                async def receiver():
                    async for message in ws:
                        try:
                            data = json.loads(message)
                        except Exception:
                            data = message
                        print(f"📥 WS 收到消息：{data}")

                # 🔥 同时跑发送 + 接收
                await asyncio.gather(sender(), receiver())

        except Exception as e:
            print(f"⚠️ WS 断开，3 秒后重连：{e}")
            await asyncio.sleep(3)



def start_ws_thread():
    def run():
        asyncio.run(ws_sender())

    t = threading.Thread(target=run, daemon=True)
    t.start()


def push_ws(nickname: str, content: str, type_: int):
    """
    type:
    1 = 弹幕
    2 = 点赞
    3 = 进入直播间
    4 = 关注
    5 = 未知
    """
    data = {
        "nickname": nickname,
        "content": content,
        "type": type_,
        "ts": int(time.time())
    }

    try:
        ws_queue.put_nowait(data)
    except Exception:
        pass

# ---------- URL / 状态判断 ----------

def get_real_url(page: Page) -> str:
    try:
        return page.evaluate("location.href")
    except Exception:
        return page.url


def update_listen_state(page: Page, reason: str = "") -> None:
    global is_listening
    url = get_real_url(page)

    should_listen = url.startswith(LIVE_URL_PREFIX)
    if should_listen != is_listening:
        is_listening = should_listen
        print(f"🎧 监听状态切换：{is_listening}（{reason}） 当前URL={url}")


# ---------- 业务解析 ----------
def extract_nickname(app_msg):
    """
    兼容：
    - fromUserContact / from_user_contact
    - contact.nickname
    - displayNickname / display_nickname
    """

    from_user = (
        app_msg.get("fromUserContact")
        or app_msg.get("from_user_contact")
        or {}
    )

    contact = from_user.get("contact") or {}

    nickname = (
        contact.get("nickname")
        or from_user.get("displayNickname")
        or from_user.get("display_nickname")
    )

    return nickname or "未知用户"


def parse_app_msg(app_msg):
    msg_type = app_msg.get("msgType") or app_msg.get("msg_type")
    nickname = extract_nickname(app_msg)

    payload_b64 = app_msg.get("payload")
    payload = {}

    if payload_b64:
        try:
            payload = json.loads(
                base64.b64decode(payload_b64).decode("utf-8")
            )
        except Exception:
            payload = {}

    # ⭐ 关注
    if msg_type == 20078:
        wording = payload.get("wording", "关注了主播")
        return nickname, wording, 4

    # 👍 点赞
    if msg_type == 20122:
        wording = payload.get("wording", "")
        return nickname, wording, 2

    return nickname, "", 5




def handle_live_msg_json(inner: Dict[str, Any]) -> None:
    for m in inner.get("msg_list", []):
        seq = m.get("seq")
        if not seq or seq in seen_seq:
            continue
        seen_seq.add(seq)

        t = m.get("type")
        nickname = m.get("nickname", "")
        content = m.get("content", "")

        if t == 1:
            print(f"💬 弹幕｜{nickname}：{content}")
            push_ws(nickname, content, 1)

            if "尺寸" in content:
                audio_cmd_q.put(("PLAY_SIZE", None))
        elif t == 10005:
            print(f"👋 进场｜{nickname} 进入直播间")
            push_ws(nickname, "进入直播间", 3)

    for app_msg in inner.get("app_msg_list", []):
        seq = app_msg.get("seq")
        if seq and seq in seen_seq:
            continue
        if seq:
            seen_seq.add(seq)

        nickname, content, type_ = parse_app_msg(app_msg)

        if type_ == 2:
            print(f"👍 点赞｜{nickname} {content}")
        elif type_ == 4:
            print(f"⭐ 关注｜{nickname} {content}")
        else:
            print(f"❓ 未知｜{nickname}")

        push_ws(nickname, content, type_)


def handle_response(resp: Response) -> None:
    if not is_listening:
        return

    if TARGET_API_KEYWORD not in resp.url:
        return

    try:
        outer = resp.json()
    except Exception:
        return

    resp_json_str = outer.get("data", {}).get("respJsonStr")
    if not resp_json_str:
        return

    try:
        inner = json.loads(resp_json_str)
    except Exception:
        return

    handle_live_msg_json(inner)


# ---------- 登录态处理 ----------

def create_context(browser):
    """
    ✅ 有缓存就加载缓存
    """
    if os.path.exists(STATE_FILE):
        print("🔐 检测到登录缓存，尝试免扫码登录")
        return browser.new_context(
            storage_state=STATE_FILE,
            no_viewport=True
        )
    else:
        print("🆕 未发现登录缓存，需要扫码登录")
        return browser.new_context(no_viewport=True)


def save_login_state(context):
    """
    ✅ 登录成功后保存
    """
    context.storage_state(path=STATE_FILE)
    print("💾 登录态已缓存，下次无需扫码")



# 播放音频回调接口

def play_audio_with_callback(wav_path):
    proc = subprocess.Popen(
        ["python", "audio_player.py", wav_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    for line in proc.stdout:
        line = line.strip()
        if line == "AUDIO_FINISHED":
            on_audio_finished()
            break


def on_audio_finished():
    print("✅ hudie_caiji 收到播放完成回调")
    # 你后续逻辑写这里
    # 比如：继续采集 / 下一句 TTS / 推流

    wav_or_mp3 = random_pick_jiejie_audio()
    print("🎲 随机选中的音频：", wav_or_mp3)

    audio_player.play_audio_and_wait(wav_or_mp3)


def maybe_save_login_state(context, page):
    """
    只要当前不在登录页，就立刻保存一次登录态
    """
    if not os.path.exists(STATE_FILE):
        try:
            url = page.evaluate("location.href")
        except Exception:
            url = page.url

        if "login.html" not in url:
            context.storage_state(path=STATE_FILE)
            print("💾 登录态已缓存成功（wx_channels_state.json）")





# ---------- 主流程 ----------

def main() -> None:
    global is_listening
    # 🔥 启动 WS 客户端
    start_ws_thread()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ]
        )

        context = create_context(browser)
        page = context.new_page()

        page.on("response", handle_response)

        # 打开后台（有缓存会直接进，没缓存会跳登录）
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        print("👉 如果是首次运行，请扫码登录；已缓存则会自动进入后台")

        last_url = ""
        saved = False

        while True:
            url = get_real_url(page)

            # URL 变化
            if url != last_url:
                last_url = url
                print(f"🔁 URL 变化：{url}")
                update_listen_state(page, reason="url changed")

            # 登录成功后自动保存一次
            if (
                not saved
                and not url.startswith(LOGIN_URL)
                and LIVE_URL_PREFIX.split("/platform")[0] in url
            ):
                save_login_state(context)
                saved = True

            # 🔥 核心：只要离开 login 页，就立刻缓存
            maybe_save_login_state(context, page)

            update_listen_state(page, reason="poll")

            process_audio_commands()

            time.sleep(0.3)





def wait_until_target_time(target_time: datetime.datetime):
    """
    阻塞等待，直到系统时间 >= target_time（统一北京时间）
    """
    tz = ZoneInfo("Asia/Shanghai")

    target = target_time.replace(second=0, microsecond=0)

    print(f"⏳ 等待播放时间：{target.strftime('%Y-%m-%d %H:%M:%S')}（北京时间）")

    while True:
        now = datetime.datetime.now(tz)  # ✅ 用带时区的 now
        if now >= target:
            break
        time.sleep(0.2)



def get_next_minute_time_text():
    """
    生成【下一分钟】的北京时间报时文本（含年月日）
    """
    tz = ZoneInfo("Asia/Shanghai")  # 北京时间
    now = datetime.datetime.now(tz)
    next_minute = now + datetime.timedelta(minutes=1)

    year = next_minute.year
    month = next_minute.month
    day = next_minute.day
    hour = next_minute.hour
    minute = next_minute.minute

    text = (
        f"现在是北京时间，"
        f"{month} 月 {day} 日，"
        f"{hour} 点 {minute} 分。还没有点关注的哥哥姐姐叔叔阿姨们，咱么左上角的小关小注点点了"
    )

    return text, next_minute

def process_audio_commands():
    """
    主线程执行：
    - 处理播放指令
    - 尺寸插播优先级最高：清空队列并立刻播
    """
    global play_mode, current_playing

    # 正在播放就不取新任务（避免并发播放）
    if current_playing:
        return

    # 没指令就返回
    try:
        cmd, payload = audio_cmd_q.get_nowait()
    except queue.Empty:
        return

    # 尺寸插播：最高优先级，清队列、切模式、播尺寸
    if cmd == "PLAY_SIZE":
        play_mode = PlayMode.SIZE

        # 清空队列，避免尺寸后又立刻播别的乱套
        while not audio_cmd_q.empty():
            try:
                audio_cmd_q.get_nowait()
            except queue.Empty:
                break

        size_audio = random_pick_size_audio()
        print("📏 主线程开始播放尺寸音频：", size_audio)

        current_playing = True
        audio_player.play_audio_and_wait(size_audio)
        current_playing = False

        play_mode = PlayMode.RANDOM
        print("🔁 尺寸播完，恢复随机模式")
        return

    # 随机讲解播放
    if cmd == "PLAY_RANDOM":
        wav = payload
        if not wav:
            return

        # 如果此时被切到 SIZE，就丢弃随机任务
        if play_mode != PlayMode.RANDOM:
            return

        print("🎲 主线程开始播放讲解音频：", wav)

        current_playing = True
        audio_player.play_audio_and_wait(wav)
        current_playing = False
        return

def voice_report_next_minute():
    # 1️⃣ 生成下一分钟文本
    text, target_time = get_next_minute_time_text()

    print(f"📝 生成报时文本：{text}")

    # 2️⃣ 提前生成语音
    wav_path = ttsplay.call_index_tts(text)

    # 3️⃣ 等待到目标分钟
    wait_until_target_time(target_time)

    # 4️⃣ 播放
    audio_player.play_audio_and_wait(wav_path)

    # 5️⃣ 回调
    on_audio_finished()


def start_random_audio_thread():
    t = threading.Thread(target=random_play_loop, daemon=True)
    t.start()


if __name__ == "__main__":
    voice_report_next_minute()
    # main()