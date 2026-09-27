"""Google Gemini TTS（gemini-3.8-flash-tts / -lite-tts）。
文档 https://ai.google.dev/gemini-api/docs/generate-content/speech-generation

用 generateContent（官方标为 Legacy，但 3.8 仍支持，且响应路径有明确文档）：
  风格 → parts[].speech_metadata.style（自然语言），音色 → generationConfig.speechConfig.voiceConfig.voice
  音频 → candidates[0].content.parts[0].inlineData.data（base64）
3.8 非流式默认返回带头 WAV（24 kHz / 单声道 / 16-bit），显式要求 AUDIO_WAV。
没有 speed / seed 参数：speed 交给 ffmpeg，seed 忽略。
"""
from __future__ import annotations

import json
from urllib.parse import quote

from .base import CloudEngine, ProviderError, b64, http

BASE = "https://generativelanguage.googleapis.com/v1beta"
PAGES = 20   # 音色库翻页上限：每页 1000，最多 2 万个


class Gemini(CloudEngine):
    provider = "gemini"
    credentials = ("GEMINI_API_KEY",)
    native_speed = False

    def _h(self):
        return {"x-goog-api-key": self.cred("GEMINI_API_KEY")}

    def fetch_voices(self):
        """在线音色库（ListVoices）：每页最多 1000 个，按 next_page_token 翻完所有页（最多 PAGES 页）。
        列表按名字排序，只取第一页会把 en- 之后的音色（大部分标准音色、中文音色）都截掉。
        注册表里的标准音色排在最前（带中文说明）；在线列表里同名的（大小写不同）不再重复。拉取失败或为空时回落到注册表。"""
        out, token = [], ""
        for _ in range(PAGES):
            q = "type=prebuilt&page_size=1000" + (f"&page_token={quote(token, safe='')}" if token else "")
            _, _, body = http("GET", f"{BASE}/voices?{q}", self._h(), timeout=30)
            j = json.loads(body)
            for v in j.get("voices", []):
                vid = v.get("id") or v.get("name", "")
                g = {"female": "女", "male": "男"}.get(str(v.get("gender", "")).lower(), "")
                out.append({"voice": vid.split("/")[-1], "name": v.get("display_name") or vid, "gender": g, "lang": v.get("language_code", ""), "description": v.get("description", "")})
            token = j.get("next_page_token") or j.get("nextPageToken") or ""
            if not token:
                break
        if not out:
            return None
        std = self.static_voices()
        seen = {v["voice"].lower() for v in std}
        return std + [v for v in out if v["voice"].lower() not in seen]

    def synth(self, req):
        part = {"text": req["input"]}
        if req.get("instructions"):
            part["speech_metadata"] = {"style": req["instructions"]}
        body = {"contents": [{"role": "user", "parts": [part]}],
                "generationConfig": {"responseModalities": ["AUDIO"],
                                     "responseFormat": {"audio": {"mimeType": "AUDIO_WAV", "sampleRate": 24000}},
                                     "speechConfig": {"voiceConfig": {"voice": req.get("voice") or "Kore"}}}}
        _, _, raw = http("POST", f"{BASE}/models/{self.m['remote']}:generateContent", self._h(), body)
        j = json.loads(raw)
        try:
            data = j["candidates"][0]["content"]["parts"][0]["inlineData"]
        except (KeyError, IndexError):
            raise ProviderError(f"Gemini 没有返回音频：{json.dumps(j, ensure_ascii=False)[:300]}")
        audio = b64(data["data"])
        # 带 RIFF 头就是 wav；否则按官方默认的无头 L16 24k 单声道处理
        return (audio, "wav") if audio[:4] == b"RIFF" else (audio, "s16le:24000:1")
