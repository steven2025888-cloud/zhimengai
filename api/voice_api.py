import requests
import uuid
import hashlib
from typing import List, Dict
import os
from core.device import get_machine_code




def safe_json(r: requests.Response):
    try:
        return r.json()
    except Exception:
        raise RuntimeError(
            f"接口返回非JSON: status={r.status_code}, "
            f"content-type={r.headers.get('Content-Type')}, body={r.text[:500]}"
        )

class LicenseApi:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def login(self, license_key: str, timeout=10) -> dict:
        url = f"{self.base_url}/api/license/login"
        payload = {
            "license_key": license_key,
            "machine_code": get_machine_code()
        }

        last_err = None
        for _ in range(2):  # 重试2次
            try:
                r = requests.post(url, json=payload, timeout=timeout)
                return r.json()
            except Exception as e:
                last_err = e

        raise RuntimeError(f"授权服务器连接失败：{last_err}")

class VoiceApiClient:
    def __init__(self, base_url: str, license_key: str):
        self.base_url = base_url.rstrip("/")
        self.license_key = license_key
        self.machine_code = get_machine_code()

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.license_key}",
            "X-Machine-Code": self.machine_code
        }

    # 上传声纹模型
    def upload_model(self, wav_path: str, name: str, describe: str = "") -> Dict:
        url = f"{self.base_url}/api/voice/model/upload"
        files = {
            "file": ("model.wav", open(wav_path, "rb"), "audio/wav")
        }
        data = {
            "name": name,
            "describe": describe
        }
        r = requests.post(url, headers=self._headers(), files=files, data=data, timeout=60)
        return safe_json(r)

    # 获取模型列表
    def list_models(self) -> List[Dict]:
        url = f"{self.base_url}/api/voice/model/list"
        r = requests.get(url, headers=self._headers(), timeout=15)
        return safe_json(r)

    # 设为默认模型
    def set_default(self, model_id: int):
        url = f"{self.base_url}/api/voice/model/default"
        r = requests.post(url, headers=self._headers(), json={"model_id": model_id}, timeout=15)
        return safe_json(r)

    # 删除模型
    def delete_model(self, model_id: int):
        url = f"{self.base_url}/api/voice/model/delete"
        r = requests.post(url, headers=self._headers(), json={"model_id": model_id}, timeout=15)
        return safe_json(r)

    # 创建TTS任务
    def tts(self, model_id: int, text: str) -> Dict:
        url = f"{self.base_url}/api/voice/tts"
        r = requests.post(url, headers=self._headers(), json={
            "model_id": model_id,
            "text": text
        }, timeout=30)
        return safe_json(r)

    # 查询TTS结果（轮询用）
    def tts_result(self, task_id: str) -> Dict:
        url = f"{self.base_url}/api/voice/tts/result"
        params = {"taskId": task_id}
        r = requests.get(url, headers=self._headers(), params=params, timeout=10)
        return safe_json(r)
