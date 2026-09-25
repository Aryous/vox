"""vox 核心：CLI、HTTP API、WebUI 共用的一切操作都在这里。

数据目录 ~/.vox（位置与分类见 paths.py）：
  clips/            合成结果 wav（按请求哈希命名）
  samples/          音色样本
  history.json      合成历史（CLI / WebUI / API 共享）
  my_voices.json    自定义音色（模型 + 音色 + 指令 + 种子的组合）
  settings.json     设置（样本文本等）
  models.json       我的模型：每家添加了哪些、手动添加的模型 ID、下载过的在线模型
  models/           下载的本地模型（不进 Time Machine 备份）
缓存（在线列表、云端音色列表、新版注册表）在 ~/Library/Caches/vox，删了会重新获取。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import audio, catalog, credentials, discovery, engines, fetch, paths, providers

HOME = paths.HOME
CLIPS, SAMPLES = paths.CLIPS, paths.SAMPLES
HIST, MYV, SETTINGS = paths.HISTORY, paths.MY_VOICES, paths.SETTINGS
MPREFS = catalog.PREFS
REGISTRY_URL = os.environ.get("VOX_REGISTRY_URL", "https://raw.githubusercontent.com/Aryous/vox/main/vox/registry.json")
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


# ---------- 模型 ----------
# 「能不能用」是系统事实：本地模型下没下载、云端 Provider 连没连上（有没有 Key），不让用户开关。
# 「想不想用」是用户选择：我的模型 = 能用的模型里，用户留下的那些。
#   本地：下载了就在「我的模型」里，移除即删除文件。
#   云端：连接 Provider 后，默认带上注册表推荐的模型；用户可以从在线列表添加更多、手动填模型 ID，或移除。
def model_or_raise(mid: str) -> dict:
    m = catalog.find_model(mid)
    if not m:
        mine = [x["id"] for x in catalog.MODELS if is_mine(x)]
        raise VoxError(f"未知模型「{mid}」。我的模型：{', '.join(mine) or '（空）'}；全部可用模型见 vox models --all")
    return m


def connected(pid: str) -> bool:
    p = catalog.PROVIDERS.get(pid) or {}
    return p.get("kind") == "local" or bool(p) and all(credentials.get(c["env"]) for c in p.get("credentials", []))


def model_status(m: dict) -> str:
    if m["provider"] != "local":
        return "ready" if connected(m["provider"]) else "needs_key"
    e = engines.get(m)
    if e.is_loaded():
        return "loaded"
    if PULLS.get(m["id"], {}).get("state") == "running":
        return "downloading"
    return "ready" if e.is_ready() else "not_downloaded"


def usable(m: dict | None) -> bool:
    return bool(m) and model_status(m) in ("ready", "loaded")


def _prefs() -> dict:
    d = _load(MPREFS, {})
    return {"mine": d.get("mine", {}), "custom": d.get("custom", [])}


def _saved(pid: str, pr: dict | None = None) -> list[str]:
    """用户在这家留下的模型 ID；从没改过时 = 注册表推荐的模型。"""
    pr = pr or _prefs()
    if pid in pr["mine"]:
        return pr["mine"][pid]
    return [m["id"] for m in catalog.MODELS if m["provider"] == pid and m.get("recommended")]


def is_mine(m: dict) -> bool:
    if m["provider"] == "local":
        return model_status(m) in ("ready", "loaded", "downloading")
    return connected(m["provider"]) and m["id"] in _saved(m["provider"])


def models(provider: str | None = None, mine: bool | None = None) -> list[dict]:
    pr = _prefs()
    saved = {pid: set(_saved(pid, pr)) for pid in catalog.PROVIDERS}
    out = []
    for m in catalog.MODELS:
        if provider and m["provider"] != provider:
            continue
        st = model_status(m)
        local = m["provider"] == "local"
        d = {k: v for k, v in m.items() if k not in ("voices", "compat")}
        d.update(status=st, saved=local and st != "not_downloaded" or m["id"] in saved[m["provider"]],
                 provider_name=catalog.PROVIDERS[m["provider"]]["name"])
        d["mine"] = st in ("ready", "loaded", "downloading") if local else st == "ready" and d["saved"]
        if mine is not None and d["mine"] != mine:
            continue
        vs = m.get("voices")
        d["voice_count"] = (len(vs) if isinstance(vs, list) else None) if m["caps"].get("voices") else None
        out.append(d)
    return out


def _set_saved(pid: str, ids: list[str]):
    pr = _prefs()
    pr["mine"][pid] = list(dict.fromkeys(ids))
    _save(MPREFS, pr)


def add_model(mid: str | None = None, provider: str | None = None, remote: str | None = None, name: str | None = None) -> dict:
    """加进「我的模型」。本地模型 = 开始下载；云端已知模型 = 加入清单；云端未知模型 ID = 作为手动添加的条目登记。"""
    m = catalog.find_model(mid) if mid else None
    if not m and provider and remote:
        m = catalog.find_model(f"{provider}/{remote.strip()}")
    if m and m["provider"] == "local":
        return pull(m["id"], background=True)
    if not m:
        provider, remote = provider or (mid or "").split("/", 1)[0], (remote or (mid or "").split("/", 1)[-1]).strip()
        p = catalog.PROVIDERS.get(provider)
        if not p or p["kind"] != "cloud":
            raise VoxError(f"未知模型「{mid or remote}」；手动添加云端模型请写成 provider/模型名，例如 openai/tts-1")
        if not remote or remote == provider:
            raise VoxError("模型名不能为空")
        if not p.get("adapter"):
            raise VoxError(f"{p['name']} 没有配置适配器，不能手动添加")
        if not connected(provider):
            raise VoxError(f"先连接 {p['name']}（填 Key），再添加它的模型")
        with FILE_LOCK:
            pr = _prefs()
            pr["custom"] = [c for c in pr["custom"] if not (c["provider"] == provider and c["remote"] == remote)]
            pr["custom"].append({"provider": provider, "remote": remote, **({"name": name} if name else {})})
            _save(MPREFS, pr)
        catalog.rebuild()
        m = catalog.find_model(f"{provider}/{remote}")
    if not connected(m["provider"]):
        raise VoxError(f"先连接 {catalog.PROVIDERS[m['provider']]['name']}（填 Key），再添加它的模型")
    with FILE_LOCK:
        _set_saved(m["provider"], _saved(m["provider"]) + [m["id"]])
    return {"model": m["id"], "mine": True}


def remove_model(mid: str, delete_files: bool = False) -> dict:
    """移出「我的模型」。本地模型要删除已下载的文件，必须显式确认（delete_files）。"""
    m = model_or_raise(mid)
    if m["provider"] == "local":
        e = engines.get(m)
        path = e.local_path()
        if not delete_files:
            raise VoxError(f"移除本地模型会删除已下载的文件 {path}（{m.get('size_gb') or '?'} GB）。确认请加 --delete-files")
        if PULLS.get(m["id"], {}).get("state") == "running":
            raise VoxError("正在下载，等下载结束再删除")
        allowed = (fetch.ROOT.resolve(), (Path.home() / ".cache" / "huggingface" / "hub").resolve())
        rp = path.resolve()
        if not any(rp != root and root in rp.parents for root in allowed):
            raise VoxError(f"模型文件不在 vox 管理的目录里，不自动删除：{path}")
        with SYNTH_LOCK:
            engines.unload(m["id"])
            shutil.rmtree(rp, ignore_errors=True)
        return {"model": m["id"], "mine": False, "deleted": str(path)}
    with FILE_LOCK:
        _set_saved(m["provider"], [x for x in _saved(m["provider"]) if x != m["id"]])
        if m["source"] == "custom":
            pr = _prefs()
            pr["custom"] = [c for c in pr["custom"] if f"{c['provider']}/{c['remote']}" != m["id"]]
            _save(MPREFS, pr)
    if m["source"] == "custom":
        catalog.rebuild()
    return {"model": m["id"], "mine": False}


def discover(provider: str) -> dict:
    """向 Provider（本地为 HuggingFace）查询现在提供的 TTS 模型，结果并进目录，返回这家的全部模型。"""
    if provider not in catalog.PROVIDERS:
        raise VoxError(f"未知的 Provider「{provider}」")
    try:
        res = discovery.run(provider)
    except providers.ProviderError as e:
        raise VoxError(str(e)) from None
    providers.reset()
    return {"provider": provider, "fetched": res["fetched"], "found": len(res["items"]), "models": models(provider)}


def registry_info() -> dict:
    r = catalog.REG
    return {"updated": r.get("updated"), "from": r.get("_from"), "url": REGISTRY_URL,
            "providers": len(catalog.PROVIDERS), "models": sum(1 for m in catalog.MODELS if m["source"] == "registry")}


def registry_update(url: str | None = None) -> dict:
    """拉取新版注册表；日期比当前新才生效。注册表只是数据，不含代码。"""
    url = url or REGISTRY_URL
    try:
        _, _, body = providers.base.http("GET", url, timeout=30)
        reg = json.loads(body)
    except (providers.ProviderError, ValueError) as e:
        raise VoxError(f"拉取注册表失败（{url}）：{e}") from None
    if not catalog.valid(reg):
        raise VoxError("拉到的文件不是 vox 注册表（schema 不对）")
    unknown = sorted({p.get("adapter") for p in reg["providers"].values() if p.get("kind") == "cloud"} - set(providers.ADAPTERS))
    if unknown:
        raise VoxError(f"新注册表需要这个版本没有的适配器：{', '.join(unknown)}。请先升级 vox")
    cur = catalog.REG.get("updated", "")
    if str(reg.get("updated", "")) <= str(cur):
        return {**registry_info(), "changed": False}
    _save(catalog.UPDATED, reg)
    catalog.rebuild()
    providers.reset()
    return {**registry_info(), "changed": True}


def _engine(m: dict):
    if m["provider"] != "local":
        e = providers.engine_for(m)
        if not e.is_ready():
            p = catalog.PROVIDERS[m["provider"]]
            raise VoxError(f"{p['name']} 还没连接：vox keys set {m['key_env']}，或在 WebUI「模型」页选中这家后填 Key（申请地址 {p['console']}）")
        return e
    e = engines.get(m)
    if not e.is_ready():
        raise VoxError(f"模型 {m['id']} 还没下载：vox models add {catalog.short(m)}（约 {m.get('size_gb') or '?'} GB）")
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
        engines.unload(m["id"])
    return {"model": m["id"], "status": model_status(m)}


def _keep_local(m: dict):
    """在线查到的本地模型一旦下载，就登记进 models.json，之后在线列表变了也还认得它。"""
    if m["source"] != "discovered":
        return
    keep = ("id", "alias", "repo", "name", "params_b", "quant", "size_gb", "homepage", "about")
    tpl = next((r["template"] for r in (discovery.cached("local") or {}).get("items", []) if r.get("id") == m["id"]), None)
    with FILE_LOCK:
        pr = _prefs()
        if not any(c.get("id") == m["id"] for c in pr["custom"]):
            pr["custom"].append({"provider": "local", "template": tpl, **{k: m.get(k) for k in keep}})
            _save(MPREFS, pr)


def pull(mid: str, background=False, source="modelscope") -> dict:
    m = model_or_raise(mid)
    if m["provider"] != "local":
        raise VoxError("云端模型无需下载")
    if m["engine"] == "kokoro":
        raise VoxError("Kokoro 首次合成时会自动下载（约 330 MB）")
    _keep_local(m)

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
    total = sum(x.get("size", 0) for x in man if x.get("type") == "file") or int((m.get("size_gb") or 0) * 1e9)
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
    """音色库：默认只列「我的模型」的音色；指定 model 时列这个模型的全部音色（添加前也能看）。"""
    out = []
    target = catalog.find_model(model) if model else None
    if model and not target:
        raise VoxError(f"未知模型「{model}」")
    for m in catalog.MODELS:
        if (target and m is not target) or (not target and not is_mine(m)) or not m["caps"].get("voices"):
            continue
        sm = catalog.short(m)
        if m["provider"] == "local":
            vs = m.get("voices")
            if vs == "engine":   # Kokoro：音色清单来自模型仓库
                try:
                    ids = engines.get(m).voices()
                except Exception:
                    ids = []
                vs = [{"voice": vid, "name": f"{'女' if vid.startswith('zf_') else '男'}声 {vid[3:]}", "gender": "女" if vid.startswith("zf_") else "男",
                       "lang": "中文", "description": f"Kokoro 中文{'女' if vid.startswith('zf_') else '男'}声 #{vid[3:]}"} for vid in ids]
        else:   # 云端：有 Key 时用在线音色列表（缓存一天），否则用注册表里的静态音色
            vs = providers.engine_for(m).voices()
        for v in vs or []:
            out.append({"ref": f"{sm}:{v['voice']}", "model": m["id"], "voice": v["voice"], "name": v.get("name") or v["voice"], "gender": v.get("gender", ""),
                        "lang": v.get("lang", ""), "description": v.get("description", ""), "kind": "preset", "cloud": m["provider"] != "local"})
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
            v["ready"] = usable(catalog.find_model(v["model"] or ""))
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
            "loaded": engines.loaded(),
            "asr": bool(shutil.which("coli")), "ffmpeg": bool(shutil.which("ffmpeg")), **paths.summary()}


# ---------- Provider 与凭证 ----------
def provider_list() -> list[dict]:
    """Provider 列表与连接状态（凭证只给是否配置、来源、末 4 位，绝不返回凭证本身）。"""
    out = []
    for pid, p in catalog.PROVIDERS.items():
        ms = models(pid)
        d = discovery.supported(pid)
        c = discovery.cached(pid) if d else None
        out.append({"id": pid, **{k: v for k, v in p.items() if k not in ("credentials", "optional", "compat", "model_defaults", "discover")},
                    "credentials": [{**c_, **credentials.status(c_["env"])} for c_ in p.get("credentials", [])],
                    "optional": [{**c_, **credentials.status(c_["env"])} for c_ in p.get("optional", [])],
                    "connected": connected(pid),
                    "discover": {"public": bool(d.get("public")), "note": d.get("note"), "fetched": c and c.get("fetched")} if d else None,
                    "count": len(ms), "mine": sum(1 for m in ms if m["mine"])})
    return out


def _forget_voice_failures(env: str):
    """换了 Key 就清掉之前拉音色失败的记录，让新 Key 立刻生效。"""
    for pid, p in catalog.PROVIDERS.items():
        if any(c["env"] == env for c in p.get("credentials", []) + p.get("optional", [])):
            for f in providers.base.CACHE.glob(f"{pid}__*.fail"):
                f.unlink(missing_ok=True)


def _known_env(env: str) -> bool:
    return any(c["env"] == env for p in catalog.PROVIDERS.values() for c in p.get("credentials", []) + p.get("optional", []))


def set_key(env: str, value: str) -> dict:
    if not _known_env(env):
        raise VoxError(f"不认识的凭证名 {env}")
    if not value.strip():
        raise VoxError("值不能为空")
    credentials.set(env, value)
    _forget_voice_failures(env)
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
