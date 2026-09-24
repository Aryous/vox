"""OpenAI 兼容适配器：POST {base}/audio/speech，返回裸音频。
一份代码覆盖 OpenAI、Inworld、阶跃星辰、硅基流动、OpenRouter；差异都写在注册表的 `compat` 配置中：

  base            默认 base URL（可用 <PROVIDER>_BASE_URL 环境变量覆盖，如接代理或国际站）
  auth            Authorization 前缀，默认 Bearer
  instructions    指令怎么传："instructions" / "instruction"（阶跃，单数）/ "prefix"（硅基：写进 input，
                  `指令<|endofprompt|>正文`）/ None（不支持）
  english_only    指令必须英文（Inworld）
  speed           [最小, 最大]，超出按边界裁剪；null 表示不传 speed，改由 ffmpeg 变速（OpenRouter：各家支持不一）
  voice_prefix    音色要带模型前缀（硅基：FunAudioLLM/CosyVoice2-0.5B:alex）
  extra           每次请求附加的固定字段
"""
from __future__ import annotations

import json
import re

from .. import credentials
from .base import CloudEngine, ProviderError, clamp, http

CJK = re.compile(r"[㐀-鿿぀-ヿ가-힯]")


class OpenAICompat(CloudEngine):
    def __init__(self, model):
        super().__init__(model)
        self.c = model["compat"]
        self.provider = model["provider"]
        self.credentials = (model["key_env"],)

    @property
    def base(self):
        return (credentials.get(self.c.get("base_env", "")) if self.c.get("base_env") else None) or self.c["base"]

    def _h(self):
        return {"Authorization": f"{self.c.get('auth', 'Bearer')} {self.cred(self.m['key_env'])}"}

    def fetch_voices(self):
        lv = self.c.get("list_voices")
        if not lv:
            return None
        _, _, raw = http("GET", lv["url"], self._h(), timeout=30)
        j = json.loads(raw)
        if lv["kind"] == "inworld":
            return [{"voice": v["voiceId"], "name": v.get("displayName") or v["voiceId"], "gender": "",
                     "lang": v.get("langCode") or v.get("languageCode", ""), "description": v.get("description", "")} for v in j.get("voices", [])]
        if lv["kind"] == "stepfun":
            det = j.get("voices-details", {})
            return [{"voice": vid, "name": det.get(vid, {}).get("voice-name", vid), "gender": "",
                     "lang": "中文", "description": det.get(vid, {}).get("voice-description", "")} for vid in j.get("voices", [])]
        return None

    @property
    def native_speed(self):
        return self.c.get("speed", (0.25, 4)) is not None

    def synth(self, req):
        c, text = self.c, req["input"]
        body = {"model": self.m["remote"], "voice": req.get("voice") or self.m.get("default_voice"), "response_format": "mp3", **c.get("extra", {})}
        if c.get("voice_prefix") and body["voice"] and ":" not in body["voice"]:
            body["voice"] = f"{self.m['remote']}:{body['voice']}"
        instr = (req.get("instructions") or "").strip()
        if instr:
            mode = c.get("instructions")
            if c.get("english_only") and CJK.search(instr):
                raise ProviderError(f"{self.m['name']} 的 instructions 只能写英文（官方要求），例如 speak warmly and slowly")
            if mode == "prefix":
                text = f"{instr}<|endofprompt|>{text}"
            elif mode:
                body[mode] = instr
        body["input"] = text
        if not body.get("voice"):
            body.pop("voice")   # 有的模型没有预置音色（如 OpenRouter 上的 Fish Audio），不传由 Provider 用默认
        if float(req.get("speed", 1)) != 1 and self.native_speed:
            lo, hi = c.get("speed", (0.25, 4))
            body["speed"] = clamp(float(req["speed"]), lo, hi)
        _, headers, audio = http("POST", f"{self.base}/audio/speech", self._h(), body)
        if audio[:1] == b"{":  # 少数情况下返回 JSON（如阶跃 return_url），不当音频处理
            raise ProviderError(f"没有返回音频：{audio[:300].decode('utf-8', 'replace')}")
        return audio, "mp3"
