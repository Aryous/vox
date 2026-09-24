"""云端适配器的公共部分：HTTP、错误、凭证、音色缓存、参数换算。

每个适配器实现：
  synth(req) -> (音频字节, 格式)   req 是网关统一请求（model/input/voice/instructions/speed/seed/lang…）
  fetch_voices() -> list[dict]     可选：从 Provider 拉音色列表（结果缓存一天）
  list_models() -> list[dict]      可选：向 Provider 查询它提供的 TTS 模型（[{remote, name, description}]），
                                   同时把 can_list_models 设为 True
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import credentials

CACHE = Path(os.environ.get("VOX_HOME", Path.home() / ".cache" / "vox")) / "voices"
UA = "vox-tts/0.2 (+https://github.com/Aryous/vox)"


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
        raise ProviderError(f"连不上 {url.split('/')[2]}：{e.reason}") from None
    except TimeoutError:
        raise ProviderError(f"请求超时（{timeout}s）") from None


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

    def __init__(self, model: dict):
        self.m = model

    # ---- 凭证 ----
    def cred(self, env: str, required=True) -> str | None:
        v = credentials.get(env)
        if required and not v:
            raise ProviderError(f"还没配置 {env}：vox keys set {env}，或在 WebUI「模型」页选中这家后粘贴")
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
        """优先用缓存的在线音色列表；没有 Key 或拉取失败时回落到目录里的静态音色。"""
        f = CACHE / f"{self.m['id'].replace('/', '__')}.json"
        if not refresh and f.exists() and time.time() - f.stat().st_mtime < self.voice_ttl:
            try:
                return json.loads(f.read_text())
            except Exception:
                pass
        if self.is_ready():
            try:
                vs = self.fetch_voices()
                if vs:
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_text(json.dumps(vs, ensure_ascii=False))
                    return vs
            except ProviderError:
                pass
        return self.static_voices()

    # ---- 模型列表 ----
    can_list_models = False

    def list_models(self) -> list[dict]:
        raise ProviderError("这家没有公开的模型列表接口")

    # ---- 合成 ----
    def synth(self, req: dict) -> tuple[bytes, str]:
        raise NotImplementedError
