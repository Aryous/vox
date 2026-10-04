"""小米 MiMo TTS：OpenAI chat/completions + audio 形态。
文档 https://mimo.mi.com/docs/en-US/api/audio/tts

注意角色是反的：要读的文本放在 assistant 消息里；user 消息只放风格指令（不会被读出来）。
- mimo-v2.5-tts：可选 audio.voice（内置 8 个音色），user 消息可选
- mimo-v2.5-tts-voicedesign：不接受 voice，user 消息（声音描述）必填
- mimo-v2.5-tts-voiceclone：audio.voice 必填，只能是参考录音的 base64 data URI（每次请求都带，不留 ID；编码后 ≤10 MB）
没有 speed / seed：speed 交给 ffmpeg，seed 忽略。
"""
from __future__ import annotations

import json

from .base import CloudEngine, ProviderError, b64, clone_file, data_uri, http

BASE = "https://api.xiaomimimo.com/v1"


class MiMo(CloudEngine):
    provider = "mimo"
    credentials = ("MIMO_API_KEY",)
    native_speed = False

    def synth(self, req):
        design = self.m["remote"].endswith("voicedesign")
        msgs = []
        if req.get("instructions"):
            msgs.append({"role": "user", "content": req["instructions"]})
        elif design:
            raise ProviderError("声音设计模型需要 instructions 描述声音")
        msgs.append({"role": "assistant", "content": req["input"]})
        audio = {"format": "wav"}
        if self.m["remote"].endswith("voiceclone"):
            if not req.get("_clone"):
                raise ProviderError("MiMo 克隆模型只能用克隆音色（-v clone:<id>）")
            audio["voice"] = data_uri(clone_file(req["_clone"])[0])
        elif not design:
            audio["voice"] = req.get("voice") or "mimo_default"
        body = {"model": self.m["remote"], "messages": msgs, "audio": audio, "stream": False}
        _, _, raw = http("POST", f"{BASE}/chat/completions", {"Authorization": f"Bearer {self.cred('MIMO_API_KEY')}"}, body)
        j = json.loads(raw)
        try:
            data = j["choices"][0]["message"]["audio"]["data"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"MiMo 没有返回音频：{json.dumps(j, ensure_ascii=False)[:300]}")
        return b64(data), "wav"
