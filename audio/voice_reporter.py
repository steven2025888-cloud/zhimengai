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

REPORT_INTERVAL_MINUTES = 15  # 默认值


def start_reporter_thread(dispatcher: AudioDispatcher, state: AppState | None = None):
    """
    兼容旧调用：voice_reporter.start_reporter_thread(dispatcher)

    实际启动逻辑：开线程跑 voice_report_loop(state, dispatcher)
    """
    st = state or app_state
    t = threading.Thread(target=voice_report_loop, args=(st, dispatcher), daemon=True)
    t.start()
    print("⏱ 已启动语音报时线程（voice_report_loop）")
    return t

def call_cloud_tts(text: str, model_id: int, timeout: int = 300) -> str:
    # 同步授权
    from api.voice_api import VoiceApiClient
    client = VoiceApiClient(BASE_URL, app_state.license_key)
    client.machine_code = app_state.machine_code

    if not client.license_key:
        raise RuntimeError("缺少授权信息：license_key 为空")

    if not model_id or int(model_id) <= 0:
        raise RuntimeError("未设置音色模型，请先添加并设为默认")

    # 🔍 打印要合成的时间文本
    print(f"🕒 准备生成报时语音：{text}（model_id={model_id}）")

    # 🔒 校验云端模型存在
    resp_models = client.list_models()
    if resp_models.get("code") != 0:
        raise RuntimeError(resp_models.get("msg", "获取模型列表失败"))

    server_ids = {int(m["id"]) for m in resp_models.get("data", [])}
    if int(model_id) not in server_ids:
        app_state.current_model_id = None
        raise RuntimeError("默认音色模型已被删除或不存在，请重新配置")

    print("✅ 云端音色模型校验通过")

    # 1. 创建TTS任务
    resp = client.tts(model_id=int(model_id), text=text)
    if resp.get("code") != 0:
        raise RuntimeError(resp.get("msg", "创建TTS任务失败"))

    data = resp["data"]
    task_id = data.get("taskId") or data.get("task_id")
    print(f"📨 TTS任务已创建：task_id={task_id}")

    # 2. 轮询结果
    start = time.time()
    interval = 0.8
    voice_url = None

    while True:
        result = client.tts_result(task_id)
        if result.get("code") != 0:
            raise RuntimeError(result.get("msg", "查询TTS结果失败"))

        rdata = result["data"]
        status = rdata.get("status")

        if status == 2:
            voice_url = rdata.get("voiceUrl") or rdata.get("voice_url")
            print("🎧 语音生成完成，云端地址：", voice_url)
            break
        elif status == 3:
            raise RuntimeError("语音合成失败")
        else:
            if time.time() - start > timeout:
                raise RuntimeError(f"TTS 超时仍未生成完成（等待 {timeout}s）")
            time.sleep(interval)
            interval = min(interval + 0.3, 3.0)

    if not voice_url:
        raise RuntimeError("云TTS未返回音频地址")

    proxy_url = f"{BASE_URL}/api/voice/tts/play?voice_url={quote(voice_url)}"
    local_file = download_voice_from_proxy(proxy_url)

    print("💾 报时音频已保存到本地：", local_file)

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



from core.runtime_state import load_runtime_state, save_runtime_state

def load_report_interval():
    global REPORT_INTERVAL_MINUTES
    state = load_runtime_state()
    REPORT_INTERVAL_MINUTES = int(state.get("report_interval_minutes", 15))
    print(f"⏱ 已加载报时间隔：{REPORT_INTERVAL_MINUTES} 分钟")

def save_report_interval(minutes: int):
    state = load_runtime_state()
    state["report_interval_minutes"] = minutes
    save_runtime_state(state)
    print(f"💾 已保存报时间隔：{minutes} 分钟")


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

    while True:
        # 🔒 总开关关闭时，直接休眠，不做任何生成
        if not state.enable_voice_report:
            time.sleep(1)
            continue

        if not state.live_ready:
            time.sleep(1)
            continue

        target = datetime.datetime.now(tz) + datetime.timedelta(minutes=REPORT_INTERVAL_MINUTES)
        target = target.replace(second=0, microsecond=0)
        pending_wav = None

        while state.enable_voice_report:
            now = datetime.datetime.now(tz)

            if pending_wav is None and now < target:
                try:
                    text = get_report_text(target)
                    pending_wav = call_cloud_tts(text, app_state.current_model_id)
                except Exception as e:
                    print("❌ 报时TTS失败：", e)
                    time.sleep(10)
                    continue

            if now >= target:
                if pending_wav and state.enable_voice_report and state.live_ready:
                    if hasattr(dispatcher, "push_report_resume"):
                        dispatcher.push_report_resume(pending_wav)
                    else:
                        dispatcher.push_report(pending_wav)

                break

            time.sleep(0.5)



