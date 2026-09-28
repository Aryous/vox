"""OpenAI 兼容适配器：合成 POST {base}/audio/speech（返回裸音频），识别 POST {base}/audio/transcriptions（multipart 上传）。
一份代码覆盖 OpenAI、Inworld、阶跃星辰、硅基流动、OpenRouter、自定义 Provider；差异都写在注册表的 `compat` 配置中。

合成：

  base            默认 base URL（可用 <PROVIDER>_BASE_URL 环境变量覆盖，如接代理或国际站）
  auth            Authorization 前缀，默认 Bearer
  instructions    指令怎么传："instructions" / "instruction"（阶跃，单数）/ "prefix"（硅基：写进 input，
                  `指令<|endofprompt|>正文`）/ None（不支持）
  english_only    指令必须英文（Inworld）
  speed           [最小, 最大]，超出按边界裁剪；null 表示不传 speed，改由 ffmpeg 变速（OpenRouter：各家支持不一）
  voice_prefix    音色要带模型前缀（硅基：FunAudioLLM/CosyVoice2-0.5B:alex）
  extra           每次请求附加的固定字段

识别（注册表 providers.<id>.stt.compat 与 stt_models[].compat）：
  response        要的返回格式：json（只有文本）/ verbose_json（分句 + 逐词时间戳，whisper-1）/ diarized_json（带说话人）
  chunking        chunking_strategy（OpenAI 的说话人分离要求长于 30 秒的音频传 auto）
  formats         对方接受的文件格式；不在列表里的先转 mp3
  max_mb          上传大小上限；超过的先压缩
  语种统一用 language 字段（OpenAI API 参考如此；指南里写 gpt-transcribe 用复数 languages，两处不一致，待用真 Key 核实）
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote

from .. import credentials
from pathlib import Path

from .base import CloudEngine, ProviderError, clamp, http, multipart

CJK = re.compile(r"[㐀-鿿぀-ヿ가-힯]")


def parse_voice_list(j) -> list[dict]:
    """OpenAI 兼容服务的音色列表没有统一格式，常见几种都认：
    ["af_bella", …]、{"voices": [...]}、{"data": [...]}；元素可以是字符串，或带 id / voice_id / voice / name 的对象。"""
    items = j if isinstance(j, list) else (j.get("voices") or j.get("data") or []) if isinstance(j, dict) else []
    out = []
    for v in items:
        if isinstance(v, str):
            out.append({"voice": v, "name": v, "gender": "", "lang": "", "description": ""})
        elif isinstance(v, dict):
            vid = v.get("id") or v.get("voice_id") or v.get("voice") or v.get("name")
            if vid:
                g = {"female": "女", "male": "男", "女": "女", "男": "男"}.get(str(v.get("gender", "")).lower(), "")
                out.append({"voice": str(vid), "name": v.get("name") or str(vid), "gender": g,
                            "lang": v.get("lang") or v.get("language") or "", "description": v.get("description") or ""})
    return out


def parse_transcription(j: dict) -> dict:
    """OpenAI 的三种 JSON 返回（json / verbose_json / diarized_json）统一成 vox 的识别结果。"""
    segs = [{"start": float(x.get("start", 0)), "end": float(x.get("end", 0)), "text": str(x.get("text", "")).strip(),
             **({"speaker": str(x["speaker"])} if x.get("speaker") not in (None, "") else {})} for x in j.get("segments") or []]
    words = [{"start": float(w.get("start", 0)), "end": float(w.get("end", 0)), "word": w.get("word", "")} for w in j.get("words") or []]
    return {"text": (j.get("text") or " ".join(x["text"] for x in segs)).strip(), "language": j.get("language"),
            "duration": j.get("duration"), "segments": segs, "words": words}


class OpenAICompat(CloudEngine):
    def __init__(self, model):
        super().__init__(model)
        self.c = model["compat"]
        self.provider = model["provider"]
        self.credentials = (model["key_env"],) if model.get("key_env") else ()   # 自建服务可以不要 Key

    @property
    def base(self):
        return (credentials.get(self.c.get("base_env", "")) if self.c.get("base_env") else None) or self.c["base"]

    def _h(self):
        if not self.credentials:
            return {}
        return {"Authorization": f"{self.c.get('auth', 'Bearer')} {self.cred(self.m['key_env'])}"}

    def fetch_voices(self):
        lv = self.c.get("list_voices")
        if not lv:
            return None
        url = lv["url"].replace("{base}", self.base).replace("{model}", quote(self.m["remote"], safe=""))
        _, _, raw = http("GET", url, self._h(), timeout=30)
        j = json.loads(raw)
        if lv["kind"] == "openai":
            return parse_voice_list(j)
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

    def transcribe(self, req, audio: Path):
        c, caps = self.c, self.m["caps"]
        fmt = c.get("response", "json")
        fields = [("model", self.m["remote"]), ("response_format", fmt)]
        if req.get("language"):
            fields.append(("language", req["language"]))
        if req.get("prompt") and caps.get("prompt"):
            fields.append(("prompt", req["prompt"]))
        if fmt == "verbose_json":
            fields += [("timestamp_granularities[]", "segment")] + ([("timestamp_granularities[]", "word")] if req.get("words") else [])
        if c.get("chunking"):
            fields.append(("chunking_strategy", c["chunking"]))
        body, ctype = multipart(fields, [("file", audio)])
        _, _, raw = http("POST", f"{self.base}/audio/transcriptions", {**self._h(), "Content-Type": ctype}, body, timeout=900)
        try:
            j = json.loads(raw)
        except ValueError:
            return {"text": raw.decode("utf-8", "replace").strip(), "segments": [], "words": []}   # 有的服务无视 response_format，直接回纯文本
        if not isinstance(j, dict):
            raise ProviderError(f"识别结果格式不对：{raw[:200].decode('utf-8', 'replace')}")
        return parse_transcription(j)
