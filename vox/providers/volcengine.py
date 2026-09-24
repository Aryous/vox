"""火山引擎 豆包语音合成 2.0（seed-tts-2.0）。V3 只有流式接口，这里读完整个 chunked 响应再拼起来。
POST https://openspeech.bytedance.com/api/v3/tts/unidirectional
  header：X-Api-Key（新版控制台）、X-Api-Resource-Id: seed-tts-2.0、X-Api-Request-Id: uuid
  body：req_params.text / speaker / audio_params{format, sample_rate, speech_rate} / additions（JSON 字符串）
  响应：每行一个 JSON，data 为 base64 音频块；code == 20000000 表示结束
语速：speech_rate -50..100（-50=0.5×，100=2×）。
情绪：官方 API 的方式是 additions.context_texts（只取第一条），把 instructions 原样放进去。
文档 https://www.volcengine.com/docs/6561/2528925
"""
from __future__ import annotations

import base64
import json
import uuid

from .base import CloudEngine, ProviderError, clamp, http

URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"


class Volcengine(CloudEngine):
    provider = "volcengine"
    credentials = ("VOLC_TTS_API_KEY",)

    def synth(self, req):
        speed = float(req.get("speed", 1))
        audio_params = {"format": "mp3", "sample_rate": 24000, "speech_rate": int(round(clamp((speed - 1) * 100, -50, 100)))}
        additions = {}
        if req.get("instructions"):
            additions["context_texts"] = [req["instructions"].strip()]
        body = {"user": {"uid": "vox"}, "req_params": {"text": req["input"], "speaker": req.get("voice") or self.m.get("default_voice"),
                                                       "audio_params": audio_params, "additions": json.dumps(additions, ensure_ascii=False)}}
        headers = {"X-Api-Key": self.cred("VOLC_TTS_API_KEY"), "X-Api-Resource-Id": self.m["remote"], "X-Api-Request-Id": str(uuid.uuid4())}
        _, _, raw = http("POST", URL, headers, body, timeout=180)
        chunks, done = [], False
        for line in raw.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line.startswith("{"):
                continue
            j = json.loads(line)
            code = j.get("code", 0)
            if code == 20000000:
                done = True
                break
            if code != 0:
                raise ProviderError(f"{code}：{j.get('message')}")
            if j.get("data"):
                chunks.append(base64.b64decode(j["data"]))
        if not chunks:
            raise ProviderError("豆包没有返回音频" + ("" if done else "（响应中也没有结束标志）"))
        return b"".join(chunks), "mp3"
