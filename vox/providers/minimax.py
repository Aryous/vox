"""MiniMax T2A v2：POST {base}/v1/t2a_v2，非流式默认返回 hex 编码音频。
国内 https://api.minimax.cn（当前文档），国际 https://api.minimax.io；两站 Key 与音色不通用，用 MINIMAX_BASE_URL 切换。
情绪只有枚举（voice_setting.emotion）：把 instructions 里的描述映射到枚举，映射不上就明确报错，不假装支持。
2.8 不支持 whisper；fluent 在 2.8 上文档矛盾，不开放。文本里可直接写 (laughs)(sighs) 等语气词和 <#0.5#> 停顿。
文档 https://platform.minimaxi.com/docs/api-reference/speech-t2a-http
"""
from __future__ import annotations

import json

from .. import credentials
from .base import CloudEngine, ProviderError, clamp, http

EMOTIONS = {
    "happy": ("开心", "高兴", "快乐", "愉快", "喜悦", "兴奋", "笑", "happy", "cheerful", "joy"),
    "sad": ("伤心", "难过", "悲伤", "沮丧", "失落", "哭", "sad"),
    "angry": ("生气", "愤怒", "恼火", "暴躁", "angry", "mad"),
    "fearful": ("害怕", "恐惧", "紧张", "惊恐", "fear", "scared"),
    "disgusted": ("厌恶", "恶心", "嫌弃", "disgust"),
    "surprised": ("惊讶", "吃惊", "震惊", "意外", "surprise"),
    "calm": ("平静", "冷静", "沉稳", "平和", "calm", "neutral", "旁白"),
}


def to_emotion(text: str) -> str:
    t = text.strip().lower()
    if t in EMOTIONS:
        return t
    for emo, words in EMOTIONS.items():
        if any(w in t for w in words):
            return emo
    raise ProviderError(f"MiniMax 只支持情绪枚举：{', '.join(EMOTIONS)}（可写中文，如「开心」「平静」）；复杂的语气可以在文本里用 (laughs)(sighs) 等标签")


class MiniMax(CloudEngine):
    provider = "minimax"
    credentials = ("MINIMAX_API_KEY",)

    @property
    def base(self):
        return (credentials.get("MINIMAX_BASE_URL") or "https://api.minimax.cn").rstrip("/")

    def _h(self):
        return {"Authorization": f"Bearer {self.cred('MINIMAX_API_KEY')}"}

    @staticmethod
    def _check(j):
        br = j.get("base_resp") or {}
        if br.get("status_code", 0) != 0:
            raise ProviderError(f"{br.get('status_code')}：{br.get('status_msg')}")

    def fetch_voices(self):
        _, _, raw = http("POST", f"{self.base}/v1/get_voice", self._h(), {"voice_type": "system"}, timeout=30)
        j = json.loads(raw)
        self._check(j)
        out = []
        for v in j.get("system_voice") or []:
            desc = v.get("description") or []
            out.append({"voice": v["voice_id"], "name": v.get("voice_name") or v["voice_id"], "gender": "", "lang": "",
                        "description": "；".join(desc) if isinstance(desc, list) else str(desc)})
        return out

    def synth(self, req):
        vs = {"voice_id": req.get("voice") or self.m.get("default_voice"), "speed": clamp(float(req.get("speed", 1)), 0.5, 2)}
        if req.get("instructions"):
            vs["emotion"] = to_emotion(req["instructions"])
        body = {"model": self.m["remote"], "text": req["input"], "stream": False, "voice_setting": vs,
                "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
                "language_boost": "auto", "output_format": "hex"}
        _, _, raw = http("POST", f"{self.base}/v1/t2a_v2", self._h(), body)
        j = json.loads(raw)
        self._check(j)
        hexaudio = (j.get("data") or {}).get("audio")
        if not hexaudio:
            raise ProviderError("MiniMax 没有返回音频")
        return bytes.fromhex(hexaudio), "mp3"
