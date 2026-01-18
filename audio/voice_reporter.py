# audio/voice_reporter.py

import os, json, time, datetime, threading
from zoneinfo import ZoneInfo
from pathlib import Path
import requests

from audio.audio_dispatcher import AudioDispatcher
from core.state import AppState

from core.state import app_state
from api.voice_api import VoiceApiClient

import urllib.parse
from urllib.parse import quote

from config import (
    BASE_URL
)

voice_client = VoiceApiClient(BASE_URL, app_state.license_key)




# ================== 报时间隔持久化配置 ==================

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "report_config.json")
REPORT_INTERVAL_MINUTES = 15  # 默认值



def call_cloud_tts(text: str, model_id: int, timeout: int = 300) -> str:
    if not model_id or int(model_id) <= 0:
        raise RuntimeError("未设置音色模型（model_id 不合法），请先添加/选择音色模型")


    voice_client.license_key = app_state.license_key
    voice_client.machine_code = app_state.machine_code

    # 1. 创建任务
    resp = voice_client.tts(model_id=model_id, text=text)
    if resp.get("code") != 0:
        raise RuntimeError(resp.get("msg", "创建TTS任务失败"))

    data = resp["data"]
    task_id = data.get("taskId") or data.get("task_id")
    if not task_id:
        raise RuntimeError(f"未返回 taskId: {resp}")

    # 2. 轮询
    start = time.time()
    interval = 0.8
    voice_url = None

    while True:
        result = voice_client.tts_result(task_id)
        if result.get("code") != 0:
            raise RuntimeError(result.get("msg", "查询TTS结果失败"))

        rdata = result["data"]
        status = rdata.get("status")

        if status == 2:
            voice_url = rdata.get("voiceUrl") or rdata.get("voice_url")
            break
        elif status == 3:
            raise RuntimeError("语音合成失败")
        else:
            if time.time() - start > timeout:
                raise RuntimeError(f"TTS 超时仍未生成完成（等待 {timeout}s）")
            time.sleep(interval)
            # 逐步放慢轮询，减轻接口压力
            interval = min(interval + 0.3, 3.0)


    if not voice_url:
        raise RuntimeError("云TTS未返回音频地址")



    # 返回给播放器的是你自己服务器的播放代理地址
    proxy_url = f"{BASE_URL}/api/voice/tts/play?voice_url={quote(voice_url)}"
    local_file = download_voice_from_proxy(proxy_url)
    return local_file



def download_voice_from_proxy(play_url: str) -> str:
    audio_dir = Path("audio_cache")
    audio_dir.mkdir(exist_ok=True)

    r = requests.get(play_url, timeout=60)
    r.raise_for_status()

    content_type = r.headers.get("Content-Type", "")
    if "wav" in content_type:
        ext = "wav"
    elif "mpeg" in content_type or "mp3" in content_type:
        ext = "mp3"
    else:
        ext = "dat"

    local_path = audio_dir / f"tts_{int(time.time()*1000)}.{ext}"
    local_path.write_bytes(r.content)

    return str(local_path)


def download_audio(voice_url: str) -> str:
    audio_dir = Path("audio_cache")
    audio_dir.mkdir(exist_ok=True)

    ext = voice_url.split("?")[0].split(".")[-1]
    if ext.lower() not in ("mp3", "wav", "aac", "ogg"):
        ext = "mp3"

    local = audio_dir / f"tts_{int(time.time()*1000)}.{ext}"

    r = requests.get(voice_url, timeout=30)
    r.raise_for_status()
    local.write_bytes(r.content)

    return str(local)



def load_report_interval():
    global REPORT_INTERVAL_MINUTES
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                REPORT_INTERVAL_MINUTES = int(data.get("interval", 15))
                print(f"⏱ 已加载报时间隔配置：{REPORT_INTERVAL_MINUTES} 分钟")
    except Exception as e:
        print("⚠ 读取报时间隔配置失败，使用默认15分钟：", e)
        REPORT_INTERVAL_MINUTES = 15

def save_report_interval(minutes: int):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"interval": minutes}, f, ensure_ascii=False, indent=2)
    print(f"💾 已保存报时间隔配置：{minutes} 分钟")

# 模块加载时自动读取
load_report_interval()

# ========================================================

def get_report_text(now: datetime.datetime) -> str:
    return (
        f"现在是北京时间，"
        f"{now.month} 月 {now.day} 日，"
        f"{now.hour} 点 {now.minute} 分。"
    )

def generate_and_push_report(target_time: datetime.datetime, dispatcher: AudioDispatcher):
    try:
        text = get_report_text(target_time)
        print("🕒 WS生成报时文本：", text)
        wav = call_cloud_tts(text, app_state.current_model_id)

        print("🎧 WS报时语音生成完成：", wav)
        dispatcher.push_report(wav)
    except Exception as e:
        print("❌ WS报时生成失败：", e)

def schedule_report_after(minutes: int, state: AppState, dispatcher: AudioDispatcher):
    tz = ZoneInfo("Asia/Shanghai")
    target = datetime.datetime.now(tz) + datetime.timedelta(minutes=minutes)
    target = target.replace(second=0, microsecond=0)

    def worker():
        try:
            text = get_report_text(target)
            print(f"🕒 预生成 {minutes} 分钟后报时文本：", text)
            wav_path = call_cloud_tts(text, app_state.current_model_id)

            print("✅ 预生成报时语音成功：", wav_path)

            while datetime.datetime.now(tz) < target:
                time.sleep(0.2)

            if state.enabled:
                print("⏰ 到点插播（WS定时）报时：", wav_path)
                dispatcher.push_report(wav_path)
        except Exception as e:
            print("❌ WS定时报时失败：", e)

    threading.Thread(target=worker, daemon=True).start()

def voice_report_loop(state: AppState, dispatcher: AudioDispatcher):
    tz = ZoneInfo("Asia/Shanghai")

    target = datetime.datetime.now(tz) + datetime.timedelta(minutes=REPORT_INTERVAL_MINUTES)
    target = target.replace(second=0, microsecond=0)

    pending_wav = None
    RETRY_INTERVAL_SEC = 15

    while True:
        if not state.live_ready:
            time.sleep(1)
            continue
        now = datetime.datetime.now(tz)

        if now < target and pending_wav is None:
            text = get_report_text(target)
            print(f"🕒 目标报时点（{REPORT_INTERVAL_MINUTES}分钟制）：", target.strftime("%H:%M"))
            try:
                pending_wav = call_cloud_tts(text, app_state.current_model_id)

                print("✅ 报时语音已生成：", pending_wav)
            except Exception as e:
                print("❌ TTS 生成失败，重试中：", e)
                time.sleep(RETRY_INTERVAL_SEC)
                continue

        if now >= target:
            if pending_wav and state.enabled and state.live_ready:
                print("⏰ 到点播放报时：", pending_wav)
                dispatcher.push_report_resume(pending_wav)

            else:
                print(f"⏭ 到点仍未生成成功，顺延下一个 {REPORT_INTERVAL_MINUTES} 分钟")

            pending_wav = None
            target = target + datetime.timedelta(minutes=REPORT_INTERVAL_MINUTES)
            target = target.replace(second=0, microsecond=0)
            continue

        time.sleep(0.5)
