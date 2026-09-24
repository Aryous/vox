"""OpenAI 兼容适配器：POST {base}/audio/speech，返回裸音频。
一份代码覆盖 OpenAI、Inworld、阶跃星辰、硅基流动；差异都写在目录里模型的 `compat` 配置中：

  base            默认 base URL（可用 <PROVIDER>_BASE_URL 环境变量覆盖，如接代理或国际站）
  auth            Authorization 前缀，默认 Bearer
  instructions    指令怎么传："instructions" / "instruction"（阶跃，单数）/ "prefix"（硅基：写进 input，
                  `指令<|endofprompt|>正文`）/ None（不支持）
  english_only    指令必须英文（Inworld）
  speed           (最小, 最大)，超出按边界裁剪
  voice_prefix    音色要带模型前缀（硅基：FunAudioLLM/CosyVoice2-0.5B:alex）
  extra           每次请求附加的固定字段
  list_models     GET {base}/models 的查询参数与过滤：match 模型名须包含的词，exclude 要排除的词（如语音识别模型）
                  （OpenAI / 阶跃的列表没有能力字段，只能按名字认 TTS；硅基用 type=audio，再去掉识别模型）
"""
from __future__ import annotations

import json
import re

from .. import credentials
from .base import CloudEngine, ProviderError, clamp, http

CJK = re.compile(r"[㐀-鿿぀-ヿ가-힯]")


class OpenAICompat(CloudEngine):
    native_speed = True

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
    def can_list_models(self):
        return bool(self.c.get("list_models"))

    def list_models(self):
        lm = self.c.get("list_models") or {}
        _, _, raw = http("GET", f"{self.base}/models{lm.get('query', '')}", self._h(), timeout=30)
        out = []
        for d in json.loads(raw).get("data", []):
            mid, low = d.get("id", ""), d.get("id", "").lower()
            if (lm.get("match") and lm["match"] not in low) or any(x in low for x in lm.get("exclude", ())):
                continue
            out.append({"remote": mid, "name": mid, "description": d.get("owned_by", "")})
        return sorted(out, key=lambda r: r["remote"])

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
        if float(req.get("speed", 1)) != 1:
            lo, hi = c.get("speed", (0.25, 4))
            body["speed"] = clamp(float(req["speed"]), lo, hi)
        _, headers, audio = http("POST", f"{self.base}/audio/speech", self._h(), body)
        if audio[:1] == b"{":  # 少数情况下返回 JSON（如阶跃 return_url），不当音频处理
            raise ProviderError(f"没有返回音频：{audio[:300].decode('utf-8', 'replace')}")
        return audio, "mp3"
