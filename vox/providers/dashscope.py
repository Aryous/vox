"""阿里云百炼（DashScope），两组接口：

A 组 SpeechSynthesizer（qwen-audio-3.0-tts-plus、cosyvoice-v3-*）
   POST https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer
   没配 WorkspaceId 时退回旧域名 dashscope.aliyuncs.com（官方说旧域名仍可用，但 2026-09-30 起不再加新特性）
   参数都在 input 里：text / voice / format / sample_rate / rate / seed / instruction（单数）
B 组 multimodal-generation（qwen3-tts-flash、qwen3-tts-instruct-flash）
   POST https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
   input：text / voice / language_type / instructions（复数）；没有 rate / seed，语速交给 ffmpeg

非流式两组都返回 output.audio.url（OSS 临时链接，24 小时），再下载一次。
文档 https://help.aliyun.com/zh/model-studio/cosyvoice-tts-http-api 、https://help.aliyun.com/zh/model-studio/qwen-tts-api
"""
from __future__ import annotations

import json

from .base import CloudEngine, ProviderError, clamp, http

LANG = {"chinese": "Chinese", "english": "English", "japanese": "Japanese", "korean": "Korean", "german": "German", "french": "French",
        "russian": "Russian", "portuguese": "Portuguese", "spanish": "Spanish", "italian": "Italian", "auto": "Auto"}


class DashScope(CloudEngine):
    provider = "aliyun"
    credentials = ("DASHSCOPE_API_KEY",)
    optional = ("DASHSCOPE_WORKSPACE_ID",)

    @property
    def group(self):
        return self.m["dashscope_group"]

    @property
    def native_speed(self):
        return self.group == "A"

    def _h(self):
        return {"Authorization": f"Bearer {self.cred('DASHSCOPE_API_KEY')}"}

    def synth(self, req):
        remote, voice = self.m["remote"], req.get("voice") or self.m.get("default_voice")
        instr = (req.get("instructions") or "").strip()
        if self.group == "A":
            ws = self.cred("DASHSCOPE_WORKSPACE_ID", required=False)
            host = f"https://{ws}.cn-beijing.maas.aliyuncs.com" if ws else "https://dashscope.aliyuncs.com"
            inp = {"text": req["input"], "voice": voice, "format": "mp3", "sample_rate": 24000}
            if float(req.get("speed", 1)) != 1:
                inp["rate"] = clamp(float(req["speed"]), 0.5, 2.0)
            if "seed" in req:
                inp["seed"] = int(req["seed"]) % 65536
            if instr:
                inp["instruction"] = instr
            url = f"{host}/api/v1/services/audio/tts/SpeechSynthesizer"
        else:
            inp = {"text": req["input"], "voice": voice, "language_type": LANG.get(req.get("lang", "chinese"), "Auto")}
            if instr:
                inp["instructions"] = instr
            url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
        _, _, raw = http("POST", url, self._h(), {"model": remote, "input": inp})
        j = json.loads(raw)
        if j.get("code"):
            raise ProviderError(f"{j.get('code')}：{j.get('message')}")
        audio_url = ((j.get("output") or {}).get("audio") or {}).get("url")
        if not audio_url:
            raise ProviderError(f"百炼没有返回音频地址：{json.dumps(j, ensure_ascii=False)[:300]}")
        _, _, audio = http("GET", audio_url, timeout=120)
        ext = audio_url.split("?")[0].rsplit(".", 1)[-1].lower()
        return audio, ext if ext in ("mp3", "wav", "opus", "pcm") else "mp3"
