"""vox 核心：CLI、HTTP API、WebUI 共用的一切操作都在这里。

数据目录（$VOX_HOME，默认 ~/.cache/vox）：
  models/           模型文件（vox pull）
  clips/            合成结果 wav（按请求哈希命名）
  samples/          音色样本
  history.json      合成历史（CLI / WebUI / API 共享）
  my_voices.json    自定义音色（模型 + 音色 + 指令 + 种子的组合）
  settings.json     设置（样本文本等）
  models.json       模型清单的个人设置：停用了哪些、手动添加 / 从 Provider 获取了哪些
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import copy
import threading
import time
from pathlib import Path

from . import audio, catalog, credentials, engines, fetch, providers

HOME = engines.CACHE
CLIPS, SAMPLES = HOME / "clips", HOME / "samples"
HIST, MYV, SETTINGS, MPREFS = HOME / "history.json", HOME / "my_voices.json", HOME / "settings.json", HOME / "models.json"
REQ_KEYS = ("model", "input", "voice", "instructions", "speed", "lang", "seed", *catalog.GEN)
SYNTH_LOCK = threading.RLock()   # MLX 不是线程安全的：合成与加载串行
FILE_LOCK = threading.Lock()
PULLS: dict[str, dict] = {}


class VoxError(ValueError):
    """可展示给用户的错误。"""


# ---------- 小工具 ----------
def _load(p: Path, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _save(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    tmp.replace(p)


def _migrate():
    """把旧版 WebUI 数据（~/.cache/vox/webui）搬到新位置，只做一次。"""
    old = HOME / "webui"
    if not old.exists() or HIST.exists():
        return
    hist = []
    for h in _load(old / "history.json", []):
        p = dict(h.get("params", {}))
        eng = p.pop("engine", "qwen3")
        if "instruct" in p:
            p["instructions"] = p.pop("instruct")
        req = {"model": "local/" + eng, "input": h.get("text", ""), **p}
        hist.append({"id": h["id"], "ts": h["ts"], "source": "webui", "request": req, "dur": h["dur"], "elapsed": h["elapsed"], "asr": h.get("asr"), "star": h.get("star", False)})
    CLIPS.mkdir(parents=True, exist_ok=True)
    for f in (old / "clips").glob("*.wav"):
        shutil.copy2(f, CLIPS / f.name)
    _save(HIST, hist)
    presets = _load(old / "presets.json", [])
    if presets and not MYV.exists():
        _save(MYV, [{"id": re.sub(r"\W+", "-", p["name"]).strip("-").lower() or f"v{i}", "name": p["name"], **_norm_voice_params(p["params"])} for i, p in enumerate(presets)])


def _norm_voice_params(p):
    p = dict(p)
    if "engine" in p:
        p["model"] = "local/" + p.pop("engine")
    if "instruct" in p:
        p["instructions"] = p.pop("instruct")
    return {k: v for k, v in p.items() if k in REQ_KEYS}


_migrate()


# ---------- 模型 ----------
def model_or_raise(mid: str) -> dict:
    m = catalog.find_model(mid)
    if not m:
        raise VoxError(f"未知模型「{mid}」。可用：{', '.join(x['id'] for x in catalog.MODELS)}")
    return m


def model_status(m: dict) -> str:
    if m.get("status") == "planned":
        return "planned"
    if m["provider"] != "local":
        return "ready" if providers.engine_for(m).is_ready() else "needs_key"
    e = engines.get(m["engine"])
    if e.is_loaded():
        return "loaded"
    if PULLS.get(m["id"], {}).get("state") == "running":
        return "downloading"
    return "ready" if e.is_ready() else "not_downloaded"


def models(provider: str | None = None) -> list[dict]:
    off = set(_prefs()["disabled"])
    out = []
    for m in catalog.MODELS:
        if provider and m["provider"] != provider:
            continue
        d = {k: v for k, v in m.items() if k not in ("engine", "voices", "compat")}
        d["status"] = model_status(m)
        d["enabled"] = m["id"] not in off
        d["provider_name"] = catalog.PROVIDERS[m["provider"]]["name"]
        d["voice_count"] = len(voices(model=m["id"], with_samples=False)) if m["caps"].get("voices") else None
        out.append(d)
    return out


# ---------- 模型清单：Provider 与模型解耦 ----------
# Provider 只管连接（凭证、地址）；模型是清单里的条目，可以启用 / 停用，也可以从 Provider 获取更多、或手动添加。
# 新增的模型借用同一家已登记模型的适配器配置（同一家的请求格式相同），只换 remote 模型名；能力按同家推断。
def _prefs() -> dict:
    return {"disabled": [], "custom": [], **_load(MPREFS, {})}


def _template(provider: str) -> dict:
    for m in catalog.MODELS:
        if m["provider"] == provider and not m.get("custom"):
            return m
    raise VoxError(f"{provider} 没有可借用的模型模板，不能添加")


def _custom_model(c: dict) -> dict:
    t = _template(c["provider"])
    m = copy.deepcopy(t)
    m.update({"id": f"{c['provider']}/{c['remote']}", "remote": c["remote"], "name": c.get("name") or c["remote"], "custom": True,
              "about": c.get("about") or f"从 {catalog.PROVIDERS[c['provider']]['name']} 获取的模型；请求格式与能力按同家的「{t['name']}」推断。",
              "price": None, "homepage": None})
    m.pop("alias", None)
    return m


def _register_customs():
    known = {m["id"] for m in catalog.MODELS}
    for c in _prefs()["custom"]:
        if c.get("provider") in catalog.PROVIDERS and f"{c['provider']}/{c['remote']}" not in known:
            catalog.MODELS.append(_custom_model(c))


def discover(provider: str) -> list[dict]:
    """向 Provider 查询它现在提供的 TTS 模型，并标出清单里已有的。"""
    p = catalog.PROVIDERS.get(provider)
    if not p or p["kind"] != "cloud":
        raise VoxError(f"未知的云端 Provider「{provider}」")
    e = providers.engine_for(_template(provider))
    if not e.can_list_models:
        raise VoxError(f"{p['name']} 没有公开的模型列表接口，只能手动添加模型 ID")
    if not e.is_ready():
        raise VoxError(f"先配置 {p['name']} 的 Key，再获取模型")
    have = {m["remote"]: m["id"] for m in catalog.MODELS if m["provider"] == provider}
    return [{**r, "provider": provider, "id": have.get(r["remote"], f"{provider}/{r['remote']}"), "added": r["remote"] in have} for r in e.list_models()]


def add_model(provider: str, remote: str, name: str | None = None) -> dict:
    remote = remote.strip()
    if provider not in catalog.PROVIDERS or catalog.PROVIDERS[provider]["kind"] != "cloud":
        raise VoxError(f"未知的云端 Provider「{provider}」")
    if not remote or "/" in remote and provider != "siliconflow":
        raise VoxError("模型 ID 不能为空，也不要带 Provider 前缀（例如填 tts-1，而不是 openai/tts-1）")
    mid = f"{provider}/{remote}"
    with FILE_LOCK:
        pr = _prefs()
        if not any(m["id"] == mid for m in catalog.MODELS):
            c = {"provider": provider, "remote": remote, **({"name": name} if name else {})}
            catalog.MODELS.append(_custom_model(c))
            pr["custom"].append(c)
        pr["disabled"] = [x for x in pr["disabled"] if x != mid]
        _save(MPREFS, pr)
    return {"model": mid, "enabled": True}


def remove_model(mid: str) -> dict:
    m = model_or_raise(mid)
    if not m.get("custom"):
        raise VoxError(f"{m['id']} 是内置模型，不能删除，可以停用：vox models off {m['id']}")
    with FILE_LOCK:
        pr = _prefs()
        pr["custom"] = [c for c in pr["custom"] if f"{c['provider']}/{c['remote']}" != m["id"]]
        pr["disabled"] = [x for x in pr["disabled"] if x != m["id"]]
        _save(MPREFS, pr)
        catalog.MODELS.remove(m)
    return {"model": m["id"], "removed": True}


def set_enabled(mid: str, on: bool) -> dict:
    m = model_or_raise(mid)
    with FILE_LOCK:
        pr = _prefs()
        pr["disabled"] = [x for x in pr["disabled"] if x != m["id"]] + ([] if on else [m["id"]])
        _save(MPREFS, pr)
    return {"model": m["id"], "enabled": on}


def _engine(m: dict):
    if m["provider"] != "local":
        e = providers.engine_for(m)
        if not e.is_ready():
            p = catalog.PROVIDERS[m["provider"]]
            raise VoxError(f"{p['name']} 还没配置 Key：vox keys set {m['key_env']}，或在 WebUI「模型」页选中这家后粘贴（申请地址 {p['console']}）")
        return e
    e = engines.get(m["engine"])
    if not e.is_ready():
        raise VoxError(f"模型 {m['id']} 还没下载：vox pull {catalog.short(m)}（约 {m.get('size_gb', '?')} GB）")
    return e


def load(mid: str) -> dict:
    m = model_or_raise(mid)
    e = _engine(m)
    with SYNTH_LOCK:
        t = time.time()
        e._load()
    return {"model": m["id"], "status": "loaded", "seconds": round(time.time() - t, 1)}


def unload(mid: str) -> dict:
    m = model_or_raise(mid)
    with SYNTH_LOCK:
        engines.unload(m["engine"])
    return {"model": m["id"], "status": model_status(m)}


def pull(mid: str, background=False, source="modelscope") -> dict:
    m = model_or_raise(mid)
    if m["provider"] != "local":
        raise VoxError("云端模型无需下载")
    if m["engine"] == "kokoro":
        raise VoxError("Kokoro 首次合成时会自动下载（约 330 MB）")

    def run():
        PULLS[m["id"]] = {"state": "running", "error": None, "started": time.time()}
        try:
            fetch.fetch(m["repo"], source)
            PULLS[m["id"]]["state"] = "done"
        except BaseException as e:
            PULLS[m["id"]].update(state="error", error=str(e))

    if background:
        if PULLS.get(m["id"], {}).get("state") != "running":
            threading.Thread(target=run, daemon=True).start()
        return pull_status(m["id"])
    run()
    if PULLS[m["id"]]["state"] == "error":
        raise VoxError(PULLS[m["id"]]["error"])
    return pull_status(m["id"])


def pull_status(mid: str) -> dict:
    m = model_or_raise(mid)
    st = PULLS.get(m["id"], {"state": "idle"})
    d = fetch.local_dir(m["repo"]) if m.get("repo") else None
    done = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) if d and d.exists() else 0
    man = _load(d / ".vox-manifest.json", []) if d else []
    total = sum(x.get("size", 0) for x in man if x.get("type") == "file") or int(m.get("size_gb", 0) * 1e9)
    return {"model": m["id"], **{k: v for k, v in st.items() if k != "started"}, "done": done, "total": total}


# ---------- 音色 ----------
def settings() -> dict:
    return {"sample_text": catalog.DEFAULT_SAMPLE_TEXT, "favorites": [], **_load(SETTINGS, {})}


def set_settings(**kw) -> dict:
    s = {**_load(SETTINGS, {}), **{k: v for k, v in kw.items() if v is not None}}
    _save(SETTINGS, s)
    return settings()


def _sample_key(ref: str, req: dict) -> str:
    return hashlib.sha1(json.dumps([ref, req], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def voices(model: str | None = None, lang: str | None = None, gender: str | None = None, q: str | None = None, with_samples=True) -> list[dict]:
    out = []
    off = set(_prefs()["disabled"]) if not model else set()
    for m in catalog.MODELS:
        if m["provider"] != "local" or m["id"] in off or (model and m is not catalog.find_model(model)):
            continue
        sm = catalog.short(m)
        if m["engine"] == "qwen3":
            for vid, name, g, lg, desc in catalog.QWEN3_VOICES:
                out.append({"ref": f"{sm}:{vid}", "model": m["id"], "voice": vid, "name": name, "gender": g, "lang": lg, "description": desc, "kind": "preset"})
        elif m["engine"] == "kokoro":
            try:
                vs = engines.get("kokoro").voices()
            except Exception:
                vs = []
            for vid in vs:
                g = "女" if vid.startswith("zf_") else "男"
                out.append({"ref": f"{sm}:{vid}", "model": m["id"], "voice": vid, "name": f"{g}声 {vid[3:]}", "gender": g, "lang": "中文", "description": f"Kokoro 中文{g}声 #{vid[3:]}", "kind": "preset"})
    off = set(_prefs()["disabled"]) if not model else set()
    for m in catalog.MODELS:  # 云端：有 Key 时用在线音色列表（缓存一天），否则用目录里的静态音色；停用的模型不进音色库
        if m["provider"] == "local" or not m["caps"].get("voices") or m["id"] in off or (model and m is not catalog.find_model(model)):
            continue
        sm = catalog.short(m)
        for v in providers.engine_for(m).voices():
            out.append({"ref": f"{sm}:{v['voice']}", "model": m["id"], "voice": v["voice"], "name": v.get("name") or v["voice"], "gender": v.get("gender", ""),
                        "lang": v.get("lang", ""), "description": v.get("description", ""), "kind": "preset", "cloud": True})
    for v in my_voices():
        m = catalog.find_model(v.get("model", ""))
        if model and m is not catalog.find_model(model):
            continue
        out.append({"ref": f"my:{v['id']}", "model": v.get("model"), "voice": v.get("voice"), "name": v["name"], "gender": v.get("gender", ""), "lang": v.get("lang_label", ""),
                    "description": v.get("instructions") or "自定义音色", "kind": "custom", "request": {k: v[k] for k in REQ_KEYS if k in v and k != "input"}})
    if lang:
        out = [v for v in out if lang in (v["lang"] or "")]
    if gender:
        out = [v for v in out if v["gender"] == gender]
    if q:
        ql = q.lower()
        out = [v for v in out if ql in json.dumps(v, ensure_ascii=False).lower()]
    if with_samples:
        text = settings()["sample_text"]
        for v in out:
            req = _sample_request(v, text)
            f = SAMPLES / f"{_sample_key(v['ref'], req)}.wav"
            v["sample"] = {"url": f"/samples/{f.name}", "cached": f.exists()}
            v["ready"] = model_status(catalog.find_model(v["model"])) in ("ready", "loaded") if catalog.find_model(v["model"] or "") else False
    return out


def resolve_voice(ref: str) -> dict:
    """把音色引用（qwen3:serena / my:xxx）展开成请求参数。"""
    if ref.startswith("my:"):
        v = next((x for x in my_voices() if x["id"] == ref[3:]), None)
        if not v:
            raise VoxError(f"没有自定义音色 {ref}")
        return {k: v[k] for k in REQ_KEYS if k in v and k != "input"}
    # 音色 ID 本身可能含冒号（如硅基流动），所以从左往右找第一个能匹配上模型的前缀
    for i, ch in enumerate(ref):
        if ch == ":" and catalog.find_model(ref[:i]):
            return {"model": catalog.find_model(ref[:i])["id"], "voice": ref[i + 1:]}
    raise VoxError(f"音色引用格式是 模型:音色，例如 qwen3:serena（收到 {ref}）")


def _sample_request(v: dict, text: str) -> dict:
    base = v.get("request") or {"model": v["model"], "voice": v["voice"]}
    return {**base, "input": text.replace("{name}", v["name"]), "seed": base.get("seed", catalog.SAMPLE_SEED)}


def sample(ref: str) -> dict:
    v = next((x for x in voices(with_samples=False) if x["ref"] == ref), None)
    if not v:
        raise VoxError(f"没有音色 {ref}")
    req = _sample_request(v, settings()["sample_text"])
    f = SAMPLES / f"{_sample_key(ref, req)}.wav"
    if not f.exists():
        _render(normalize(req), f)
    return {"ref": ref, "url": f"/samples/{f.name}", "file": str(f), "dur": round(audio.duration(f), 2), "text": req["input"]}


def my_voices() -> list[dict]:
    return _load(MYV, [])


def save_my_voice(name: str, request: dict, vid: str | None = None) -> dict:
    req = normalize({**request, "input": "-"}, strict=False)
    req.pop("input", None)
    vid = vid or re.sub(r"[^\w一-鿿-]+", "-", name).strip("-").lower() or f"v{int(time.time())}"
    rec = {"id": vid, "name": name, **req}
    with FILE_LOCK:
        _save(MYV, [rec] + [v for v in my_voices() if v["id"] != vid])
    return rec


def delete_my_voice(vid: str):
    with FILE_LOCK:
        _save(MYV, [v for v in my_voices() if v["id"] != vid])


# ---------- 合成 ----------
def normalize(req: dict, strict=True) -> dict:
    """统一请求：解析模型、音色引用，丢掉模型不支持的参数。"""
    req = {k: v for k, v in req.items() if v not in (None, "")}
    if "instruct" in req:
        req["instructions"] = req.pop("instruct")
    if isinstance(req.get("voice"), dict):  # OpenAI 自定义音色对象 {"id": ...}
        req["voice"] = req["voice"].get("id")
    v = req.get("voice")
    if isinstance(v, str) and (":" in v):   # 允许 voice 直接写音色引用
        req = {**resolve_voice(v), **{k: x for k, x in req.items() if k != "voice"}}
    m = model_or_raise(req.get("model") or os.environ.get("VOX_MODEL", "local/qwen3"))
    if strict and not str(req.get("input", "")).strip():
        raise VoxError("input 不能为空")
    out = {"model": m["id"], "input": str(req.get("input", "")).strip()}
    for k in m["params"]:
        if k in req:
            out[k] = req[k]
    if "speed" in out:
        out["speed"] = float(out["speed"])
        if not 0.25 <= out["speed"] <= 4:
            raise VoxError("speed 取值 0.25–4")
    if "seed" in out:
        out["seed"] = int(out["seed"])
    if m["caps"].get("voices") and not out.get("voice"):
        out["voice"] = m.get("default_voice")
    if m["caps"].get("design") and strict and not out.get("instructions"):
        raise VoxError(f"{m['id']} 需要 instructions 描述声音，例如「{catalog.DESIGN_EXAMPLES[1]}」")
    return out


def _render(req: dict, out: Path) -> float:
    """合成并写成 wav，返回时长。本地模型返回采样数组，云端返回编码后的字节，最后都落成同一种文件。"""
    m = catalog.find_model(req["model"])
    e = _engine(m)
    speed = float(req.get("speed", 1))
    if m["provider"] != "local":
        try:
            data, fmt = e.synth(req)  # 云端请求可以并发，不占本地锁
        except providers.ProviderError as err:
            raise VoxError(f"{catalog.PROVIDERS[m['provider']]['name']}：{err}") from None
        return audio.bytes_to_wav(data, fmt, out, speed, e.native_speed)
    gen = {k: req[k] for k in catalog.GEN if k in req}
    with SYNTH_LOCK:
        wav, sr = e.synth(req["input"], voice=req.get("voice"), instruct=req.get("instructions"), speed=speed,
                          lang=req.get("lang", "chinese"), seed=req.get("seed"), **gen)
    return audio.write_wav(wav, sr, out, speed, e.native_speed)


def estimate(req: dict) -> dict | None:
    """按官方价格估算这次请求的费用（只估按字符 / 字节计费的；按 token 计费的只给价格说明）。"""
    m = catalog.find_model(req.get("model", ""))
    p = (m or {}).get("price")
    if not p:
        return None
    if p.get("unit") == "token" or "amount" not in p:
        return {"text": p.get("text", ""), "amount": None}
    text = req.get("input", "")
    n = {"byte": len(text.encode()), "cjk2": sum(2 if "\u3400" <= c <= "\u9fff" else 1 for c in text)}.get(p["unit"], len(text))
    amount = p["amount"] * n / p["per"]
    sym = "¥" if p["currency"] == "CNY" else "$"
    unit = {"char": "字符", "byte": "UTF-8 字节", "cjk2": "字符（汉字按 2）"}[p["unit"]]
    per = {1000: "千", 10000: "万", 1_000_000: "百万"}.get(p["per"], f"{p['per']:,} ")
    return {"amount": round(amount, 6), "currency": p["currency"], "text": f"约 {sym}{amount:.4f}（{n} {unit} × {sym}{p['amount']} / {per}）"}


def clip_path(cid: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{16}", cid or ""):
        raise VoxError("无效的结果 ID")
    return CLIPS / f"{cid}.wav"


def speak(request: dict, source="cli", record=True) -> dict:
    """合成一条语音。同一请求（含种子）命中缓存直接返回。"""
    req = normalize(request)
    m = catalog.find_model(req["model"])
    if m["caps"].get("seed") and "seed" not in req:
        req["seed"] = int.from_bytes(os.urandom(3), "big") % 1000000  # 记录实际种子，保证可复现
    cid = hashlib.sha1(json.dumps(req, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    out = clip_path(cid)
    hit = next((h for h in history() if h["id"] == cid), None)
    if hit and out.exists():
        return {**hit, "cached": True, "file": str(out)}
    t = time.time()
    dur = _render(req, out)
    elapsed = time.time() - t
    rec = {"id": cid, "ts": time.time(), "source": source, "request": req, "dur": round(dur, 3), "elapsed": round(elapsed, 2), "asr": None, "star": False}
    if m["provider"] != "local":
        rec["cost"] = estimate(req)
        rec["reproducible"] = bool(m["caps"].get("seed"))
    if record:
        with FILE_LOCK:
            _save(HIST, [rec] + [h for h in history() if h["id"] != cid][:999])
    return {**rec, "file": str(out)}


# ---------- 历史 ----------
def history(limit: int | None = None, star: bool | None = None) -> list[dict]:
    h = _load(HIST, [])
    if star is not None:
        h = [x for x in h if bool(x.get("star")) == star]
    return h[:limit] if limit else h


def update_history(cid: str, star: bool | None = None, delete: bool = False):
    with FILE_LOCK:
        h = history()
        if delete:
            h = [x for x in h if x["id"] != cid]
            clip_path(cid).unlink(missing_ok=True)
        for x in h:
            if x["id"] == cid and star is not None:
                x["star"] = bool(star)
        _save(HIST, h)


def asr(cid: str) -> str:
    f = clip_path(cid)
    if not f.exists():
        raise VoxError("找不到这条音频")
    if not shutil.which("coli"):
        raise VoxError("读音校对需要本机的 coli（npm install -g @marswave/coli）")
    r = subprocess.run(["coli", "asr", str(f)], capture_output=True, text=True, timeout=180)
    text = (r.stdout.strip().splitlines() or [""])[-1]
    with FILE_LOCK:
        h = history()
        for x in h:
            if x["id"] == cid:
                x["asr"] = text
        _save(HIST, h)
    return text


# ---------- 状态 ----------
START = time.time()


def status() -> dict:
    rss = 0
    try:
        rss = int(subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True).stdout.strip()) * 1024
    except Exception:
        pass
    from . import __version__

    return {"version": __version__, "uptime": round(time.time() - START), "memory_bytes": rss,
            "loaded": [catalog.find_model("local/" + n)["id"] for n in engines.loaded()],
            "asr": bool(shutil.which("coli")), "ffmpeg": bool(shutil.which("ffmpeg")), "home": str(HOME)}


# ---------- Provider 与凭证 ----------
def provider_list() -> list[dict]:
    """Provider 列表与凭证状态（只给是否配置、来源、末 4 位，绝不返回凭证本身）。"""
    off = set(_prefs()["disabled"])
    out = []
    for pid, p in catalog.PROVIDERS.items():
        ms = [m for m in catalog.MODELS if m["provider"] == pid]
        cloud = p["kind"] == "cloud"
        out.append({"id": pid, **{k: v for k, v in p.items() if k not in ("credentials", "optional")},
                    "credentials": [{**c, **credentials.status(c["env"])} for c in p.get("credentials", [])],
                    "optional": [{**c, **credentials.status(c["env"])} for c in p.get("optional", [])],
                    "ready": all(credentials.get(c["env"]) for c in p.get("credentials", [])) if cloud else True,
                    "can_list_models": cloud and bool(ms) and providers.engine_for(ms[0]).can_list_models,
                    "models": [m["id"] for m in ms], "enabled": [m["id"] for m in ms if m["id"] not in off]})
    return out


def _known_env(env: str) -> bool:
    return any(c["env"] == env for p in catalog.PROVIDERS.values() for c in p.get("credentials", []) + p.get("optional", []))


def set_key(env: str, value: str) -> dict:
    if not _known_env(env):
        raise VoxError(f"不认识的凭证名 {env}")
    if not value.strip():
        raise VoxError("值不能为空")
    credentials.set(env, value)
    return credentials.status(env)


def delete_key(env: str) -> dict:
    if not _known_env(env):
        raise VoxError(f"不认识的凭证名 {env}")
    credentials.delete(env)
    return credentials.status(env)


def refresh_voices(mid: str) -> int:
    m = model_or_raise(mid)
    if m["provider"] == "local":
        return len(voices(model=m["id"], with_samples=False))
    return len(providers.engine_for(m).voices(refresh=True))


_register_customs()
