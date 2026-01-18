from gradio_client import Client, handle_file
from pathlib import Path
import socket
import subprocess
import os
import time
import sys

DEFAULT_GRADIO_URL = "http://127.0.0.1:7860/"
DEFAULT_REF_AUDIO = str(Path.home() / "Desktop" / "yinpin" / "jiangjie.WAV")

_client = None
_tts_proc = None


def is_port_open(host="127.0.0.1", port=7860, timeout=1.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def kill_port_7860():
    try:
        result = subprocess.check_output(
            'netstat -ano | findstr :7860',
            shell=True,
            text=True
        )
        for line in result.splitlines():
            parts = line.split()
            if len(parts) >= 5:
                pid = parts[-1]
                subprocess.run(f'taskkill /PID {pid} /F', shell=True)
                print(f"🔪 已关闭占用 7860 端口的进程 PID={pid}")
    except Exception:
        print("ℹ️ 当前没有进程占用 7860")


def _resolve_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)

    cwd = os.getcwd()
    if os.path.exists(os.path.join(cwd, "index-tts-main")):
        return cwd

    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


def start_index_tts():
    global _tts_proc

    base = _resolve_base_dir()
    index_dir = os.path.join(base, "index-tts-main")
    bat_path = os.path.join(index_dir, "start_tts.bat")

    if not os.path.exists(bat_path):
        raise RuntimeError("未找到 index-tts-main\\start_tts.bat")

    if is_port_open():
        print("✅ IndexTTS 已在运行")
        return

    print("🚀 正在启动 IndexTTS ...")
    _tts_proc = subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        cwd=index_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW
    )

    # 只靠端口判断，不靠 stdout
    start_ts = time.time()
    while True:
        if is_port_open():
            print("✅ IndexTTS 服务已就绪 (7860)")
            return

        if time.time() - start_ts > 180:
            raise RuntimeError("IndexTTS 启动超时（7860 端口一直未监听）")

        time.sleep(1)



def get_client_with_retry(url=DEFAULT_GRADIO_URL):
    global _client

    for round in range(2):
        try:
            print(f"🔌 尝试连接 Gradio（第 {round+1} 次）")
            for i in range(15):
                try:
                    _client = Client(url)
                    print("✅ Gradio 连接成功")
                    return _client
                except Exception as e:
                    print(f"⏳ 等待中 {i+1}/15: {e}")
                    time.sleep(1)
            raise RuntimeError("Gradio 启动超时")
        except Exception as e:
            print("❌ 连接失败：", e)
            if round == 0:
                print("♻️ 清理 7860 端口并重启 TTS")
                kill_port_7860()
                start_index_tts()
                time.sleep(5)
            else:
                raise RuntimeError("IndexTTS 服务无法启动，请检查环境")

    return _client


def ensure_index_tts_running():
    if not is_port_open():
        start_index_tts()


def call_index_tts(
    text: str,
    gradio_url: str = DEFAULT_GRADIO_URL,
    ref_audio_path: str = DEFAULT_REF_AUDIO,
) -> str:
    ensure_index_tts_running()

    print(f"🎤 请求合成：{text}")

    client = get_client_with_retry(gradio_url)

    result = client.predict(
        "与音色参考音频相同",
        handle_file(ref_audio_path),
        text,
        None,
        0.65,
        0, 0, 0, 0, 0, 0, 0, 0,
        "",
        False,
        120,
        True,
        0.8,
        30,
        0.8,
        0.0,
        3,
        10.0,
        1500,
        api_name="/tts"
    )

    if isinstance(result, dict):
        wav_path = result.get("value") or result.get("path") or result.get("name")
    elif isinstance(result, list):
        item = result[0]
        wav_path = item.get("value") if isinstance(item, dict) else item
    else:
        wav_path = result

    print(f"🎵 生成完成：{wav_path}")
    return wav_path


# ===== 测试入口 =====
if __name__ == "__main__":
    text = "你好，这是织梦AI语音系统启动自检。"
    wav = call_index_tts(text)
    print("最终音频文件：", wav)
