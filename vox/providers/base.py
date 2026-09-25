"""云端适配器的公共部分：HTTP、错误、凭证、音色缓存、参数换算。

每个适配器实现：
  synth(req) -> (音频字节, 格式)   req 是网关统一请求（model/input/voice/instructions/speed/seed/lang…）
  fetch_voices() -> list[dict]     可选：从 Provider 拉音色列表（结果缓存一天）
"""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import credentials, paths

CACHE = paths.VOICE_LISTS
UA = "vox-tts/0.2 (+https://github.com/Aryous/vox)"
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
    fail_ttl = 600

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
