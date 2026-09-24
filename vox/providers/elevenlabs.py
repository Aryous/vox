"""ElevenLabs：POST /v1/text-to-speech/{voice_id}，返回裸音频。
文档 https://elevenlabs.io/docs/api-reference/text-to-speech/convert

- instructions：v3 用音频标签控制语气，标签是开放的（如 [whispers]、[excited]、[professional]），
  所以把 instructions 包成一个前置标签；其他型号不支持，目录里不开这项能力。
- speed：v3 不接受 voice_settings.speed（官方说由标签控制），交给 ffmpeg 变速；Flash / Multilingual 原生 0.7–1.2。
- seed：官方支持（尽力确定性）。
"""
from __future__ import annotations

import json
from urllib.parse import quote

from .base import CloudEngine, ProviderError, clamp, http

BASE = "https://api.elevenlabs.io"


class ElevenLabs(CloudEngine):
    provider = "elevenlabs"
    credentials = ("ELEVENLABS_API_KEY",)

    @property
    def native_speed(self):
        return self.m["id"] != "elevenlabs/eleven_v3"

    def _h(self):
        return {"xi-api-key": self.cred("ELEVENLABS_API_KEY")}

    def fetch_voices(self):
        out, token = [], None
        for _ in range(5):  # 最多翻 5 页（500 个）
            q = "voice_type=default&page_size=100" + (f"&next_page_token={quote(token)}" if token else "")
            _, _, body = http("GET", f"{BASE}/v2/voices?{q}", self._h(), timeout=30)
            j = json.loads(body)
            for v in j.get("voices", []):
                lab = v.get("labels") or {}
                g = {"female": "女", "male": "男"}.get(str(lab.get("gender", "")).lower(), "")
                out.append({"voice": v["voice_id"], "name": v.get("name", v["voice_id"]), "gender": g,
                            "lang": lab.get("accent") or lab.get("language") or "", "description": v.get("description") or lab.get("description") or lab.get("use_case") or ""})
            token = j.get("next_page_token")
            if not j.get("has_more") or not token:
                break
        return out

    def synth(self, req):
        voice = req.get("voice")
        if not voice:
            raise ProviderError("ElevenLabs 需要 voice（voice_id），先在音色库里选一个")
        text = req["input"]
        model_id = self.m["remote"]
        if req.get("instructions") and model_id == "eleven_v3":
            text = f"[{req['instructions'].strip().strip('[]')}] {text}"
        body = {"text": text, "model_id": model_id}
        if "seed" in req:
            body["seed"] = int(req["seed"]) % 4294967296
        if model_id != "eleven_v3" and float(req.get("speed", 1)) != 1:
            body["voice_settings"] = {"speed": clamp(float(req["speed"]), 0.7, 1.2)}
        if req.get("lang") and req["lang"] != "auto":
            body["language_code"] = {"chinese": "zh", "english": "en", "japanese": "ja", "korean": "ko"}.get(req["lang"], req["lang"][:2])
        _, _, audio = http("POST", f"{BASE}/v1/text-to-speech/{quote(voice)}?output_format=mp3_44100_128", self._h(), body)
        return audio, "mp3"
