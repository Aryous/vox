"""云端适配器的公共部分：HTTP、错误、凭证、音色缓存、参数换算。

每个适配器实现：
  synth(req) -> (音频字节, 格式)       合成：req 是网关统一请求（model/input/voice/instructions/speed/seed/lang…）
  transcribe(req, 音频路径) -> dict   识别（可选）：req 为 model/language/prompt/words/diarize；返回 text / language / duration / segments / words
  fetch_voices() -> list[dict]         可选：从 Provider 拉音色列表（结果缓存一天）
适配器按协议写（一家接口一个类），同一个类可以同时实现合成和识别。
"""
from __future__ import annotations

import base64
import http.client as httpclient
import json
import mimetypes
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import __version__, credentials, paths

CACHE = paths.VOICE_LISTS
UA = f"vox-tts/{__version__} (+https://github.com/Aryous/vox)"
_PULLING: set[str] = set()   # 正在后台拉音色列表的模型


class ProviderError(ValueError):
    """Provider 返回的错误，信息可直接展示给用户（不含凭证）。"""


def http(method: str, url: str, headers: dict | None = None, body=None, timeout=120, raw=False):
    """发请求；body 为 dict 时按 JSON 发送。返回 (状态码, 响应头, 字节)。失败抛 ProviderError。"""
    data = json.dumps(body, ensure_ascii=False).encode() if isinstance(body, (dict, list)) else body
    h = {"User-Agent": UA, **({"Content-Type": "application/json"} if isinstance(body, (dict, list)) else {}), **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        payload = e.read()
        raise ProviderError(f"HTTP {e.code}：{_err_text(payload) or e.reason}") from None
    except urllib.error.URLError as e:
        raise ProviderError(f"无法连接 {url.split('/')[2]}：{e.reason}") from None
    except TimeoutError:
        raise ProviderError(f"请求超时（{timeout}s）") from None
    except (httpclient.HTTPException, ConnectionError, OSError) as e:   # 对方断开连接、返回的不是 HTTP 等
        raise ProviderError(f"{url.split('/')[2]} 连接异常：{type(e).__name__} {e}".strip()) from None


def _err_text(payload: bytes) -> str:
    try:
        j = json.loads(payload)
    except Exception:
        return payload[:300].decode("utf-8", "replace").strip()
    for path in (("error", "message"), ("error",), ("message",), ("detail", "message"), ("detail",), ("base_resp", "status_msg"), ("header", "message"), ("msg",)):
        v = j
        for k in path:
            v = v.get(k) if isinstance(v, dict) else None
        if isinstance(v, str) and v:
            return v
    return json.dumps(j, ensure_ascii=False)[:300]


def multipart(fields: list[tuple[str, str]], files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    """multipart/form-data 请求体（上传音频用）。同名字段可以重复（如 timestamp_granularities[]）。返回 (字节, Content-Type)。"""
    b = "vox" + os.urandom(12).hex()
    out = bytearray()
    for k, v in fields:
        out += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for k, p in files:
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        out += f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{p.name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()
        out += p.read_bytes() + b"\r\n"
    out += f"--{b}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={b}"


def clone_file(ref: dict, fmt: str = "wav", max_sec: float | None = None, key: str = "audio") -> tuple[Path, bool]:
    """克隆音色的参考录音（24 kHz 单声道 wav，见 clones.py），按需转成 mp3、截到 max_sec 秒。
    返回 (文件, 是否截短了)：截短后原来的文字稿就对不上了，调用方应当不再传文字稿。转换结果缓存在录音旁边。"""
    import subprocess

    src = Path(ref[key])
    dur = float(ref.get("duration") or 0) if key == "audio" else 0
    cut = bool(max_sec) and (dur == 0 or dur > max_sec)
    if fmt == "wav" and not cut:
        return src, False
    out = src.with_name(f"{src.stem}.{fmt}" if not cut else f"{src.stem}.{int(max_sec)}s.{fmt}")
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        args = ["-b:a", "192k"] if fmt == "mp3" else []
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), *(["-t", str(max_sec)] if cut else []), *args, str(out)],
                           capture_output=True, text=True)
        if r.returncode:
            raise ProviderError(f"参考录音转换失败：{r.stderr.strip()[:200]}")
    return out, cut and dur > (max_sec or 0)


def data_uri(p: Path) -> str:
    mime = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}.get(p.suffix.lower(), "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def remote_id(ref: dict, prefix: str = "vox", maxlen: int = 32, sep: str = "") -> str:
    """给云端起一个音色 ID：只用英文字母和数字，字母开头（各家规则的交集），带随机后缀避免和已有的重名。"""
    import re

    stem = re.sub(r"[^A-Za-z0-9]", "", ref.get("id", ""))[:10]
    return f"{prefix}{sep}{stem}{sep if stem else ''}{os.urandom(4).hex()}"[:maxlen]


def b64(s: str) -> bytes:
    return base64.b64decode(s)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def lerp_speed(speed: float, lo: float, hi: float, one: float = 1.0) -> float:
    """网关语速（倍数，1 为正常）换算到 Provider 的倍数区间并裁剪。"""
    return round(clamp(speed * one, lo, hi), 2)


class CloudEngine:
    """所有云端适配器的基类。子类设置 provider / credentials，并实现 synth。"""

    provider = ""
    credentials: tuple[str, ...] = ()   # 需要的环境变量名，第一个是主 Key
    optional: tuple[str, ...] = ()       # 可选的环境变量（如自定义 base URL）
    native_speed = True
    voice_ttl = 86400
    fail_ttl = 600

    def __init__(self, model: dict):
        self.m = model

    # ---- 凭证 ----
    def cred(self, env: str, required=True) -> str | None:
        v = credentials.get(env)
        if required and not v:
            raise ProviderError(f"尚未配置 {env}。配置方式：vox keys set {env}，或在网页「模型」页选择该 Provider 后填写")
        return v

    def is_ready(self) -> bool:
        return all(credentials.get(e) for e in self.credentials)

    def is_loaded(self) -> bool:
        return False

    def _load(self):
        return None

    # ---- 音色 ----
    def static_voices(self) -> list[dict]:
        return self.m.get("voices", [])

    def fetch_voices(self) -> list[dict] | None:
        return None

    def voices(self, refresh=False) -> list[dict]:
        """音色列表：先返回手头有的（缓存或注册表里的静态音色），过期了在后台更新，不让页面等网络。
        refresh=True 时同步拉取并如实报错（给「刷新音色」用）。拉取失败记一笔，10 分钟内不重试。"""
        f = CACHE / f"{self.m['id'].replace('/', '__')}.json"
        if refresh:
            return self._pull_voices(f, raise_errors=True) or self.static_voices()
        cached = None
        if f.exists():
            try:
                cached = json.loads(f.read_text())
            except Exception:
                cached = None
        fresh = cached is not None and time.time() - f.stat().st_mtime < self.voice_ttl
        fail = f.with_suffix(".fail")
        recently_failed = fail.exists() and time.time() - fail.stat().st_mtime < self.fail_ttl
        if not fresh and not recently_failed and self.is_ready() and self.m["id"] not in _PULLING:
            _PULLING.add(self.m["id"])
            threading.Thread(target=self._pull_voices, args=(f,), daemon=True).start()
        return cached or self.static_voices()

    def _pull_voices(self, f: Path, raise_errors=False) -> list[dict] | None:
        fail = f.with_suffix(".fail")
        try:
            vs = self.fetch_voices()
            if vs:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps(vs, ensure_ascii=False))
                fail.unlink(missing_ok=True)
            return vs
        except ProviderError:
            if raise_errors:
                raise
            fail.parent.mkdir(parents=True, exist_ok=True)
            fail.touch()
            return None
        finally:
            _PULLING.discard(self.m["id"])

    # ---- 合成 ----
    def synth(self, req: dict) -> tuple[bytes, str]:
        raise NotImplementedError

    # ---- 识别 ----
    def transcribe(self, req: dict, audio: Path) -> dict:
        raise ProviderError(f"{self.m['name']} 的适配器暂不支持语音识别")

    # ---- 克隆音色 ----
    # compat.clone.mode = "voice"：clone_create 把录音注册成这家的音色，返回 {"voice": 音色 ID, ...}，合成时 req["voice"] 就是这个 ID；
    #                    = "inline"：不注册，合成时 req["_clone"] 带着录音（audio 路径、text 文字稿），适配器自己放进请求。
    # ref 字段：id（vox 里的 ID）/ name / audio（24 kHz 单声道 wav 路径）/ text（文字稿，可能为空）/ lang / consent（同意声明录音路径或 None）
    def clone_create(self, ref: dict) -> dict:
        raise ProviderError(f"{self.m['name']} 的适配器暂不支持声音克隆")

    def clone_delete(self, remote: dict):
        """删除云端注册的音色（没有删除接口的厂商什么也不做）。"""
