"""语音识别（声音 → 文字）：vox transcribe、POST /v1/audio/transcriptions、WebUI「转写」共用这里。

和合成共用 hub 里的模型体系（我的模型、下载、加载、Key、Provider），这里只管识别自己的事。

请求字段（CLI / HTTP / WebUI 同一套）：
  model      识别模型（task=stt）。不填用默认：设置里的 stt_model，否则「我的模型」里第一个能用的识别模型
  language   语种提示（zh / en / ja……），不填自动识别
  prompt     上下文提示（专有名词、前文）；模型不支持就不传
  hotwords   热词列表；模型不支持就不传
  words      要逐词时间戳
  diarize    要区分说话人
  cache      false 时不用缓存、重新识别
提示类参数（prompt / hotwords）模型不支持时直接不传；结构类要求（words / diarize）不支持就报错，
因为「要字幕却只拿到一整段文本」比明确报错更糟。

结果（paths.TRANSCRIPTS/<id>.json）：
  id / ts / source / file（原文件名）/ request / text / language / duration / segments[{start,end,text,speaker?}] / words[] / elapsed / cost
  id = 文件内容哈希 + 请求：同一个文件、同样的参数直接返回上次的结果。
输出格式：txt / srt / vtt / json（render）。
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path

from . import audio, catalog, hub, paths, providers

DIR = paths.TRANSCRIPTS
VoxError = hub.VoxError
FORMATS = ("txt", "srt", "vtt", "json")


# ---------- 模型 ----------
def stt_models(mine: bool = True) -> list[dict]:
    """识别模型（默认只要「我的模型」里的），按注册表顺序。"""
    return [m for m in catalog.MODELS if m["task"] == "stt" and (not mine or hub.is_mine(m))]


def default_model() -> dict:
    pick = hub.settings().get("stt_model")
    m = catalog.find_model(pick) if pick else None
    if m and m["task"] == "stt" and hub.usable(m):
        return m
    for m in stt_models():
        if hub.usable(m):
            return m
    local = next((m for m in catalog.MODELS if m["task"] == "stt" and m["provider"] == "local"), None)
    hint = f"下载一个本地识别模型：vox models add {catalog.short(local)}（约 {local.get('size_gb')} GB）" if local else "先添加一个识别模型"
    raise VoxError(f"还没有能用的语音识别模型。{hint}；或连接支持识别的云端 Provider，见 vox models --task stt --all")


def _model(mid: str | None) -> dict:
    if not mid:
        return default_model()
    m = hub.model_or_raise(mid)
    if m["task"] != "stt":
        others = ", ".join(catalog.short(x) for x in stt_models()) or "（还没有，见 vox models --task stt --all）"
        raise VoxError(f"{m['id']} 是语音合成模型，不能识别。我的识别模型：{others}")
    return m


# ---------- 请求 ----------
def normalize(req: dict) -> dict:
    m = _model(req.get("model"))
    caps = m["caps"]
    out = {"model": m["id"]}
    lang = str(req.get("language") or "").strip().lower()
    if lang and lang != "auto":
        out["language"] = lang
    if caps.get("prompt") and str(req.get("prompt") or "").strip():
        out["prompt"] = str(req["prompt"]).strip()
    hw = req.get("hotwords")
    hw = [x.strip() for x in (hw.replace("，", ",").split(",") if isinstance(hw, str) else hw or []) if str(x).strip()]
    if caps.get("hotwords") and hw:
        out["hotwords"] = hw
    for k, need, what in (("words", "words", "逐词时间戳"), ("diarize", "diarize", "区分说话人")):
        if _truthy(req.get(k)):
            if not caps.get(need):
                able = [catalog.short(x) for x in catalog.MODELS if x["task"] == "stt" and x["caps"].get(need)]
                raise VoxError(f"{m['name']} 不支持{what}。支持的模型：{', '.join(able) or '（暂无）'}")
            out[k] = True
    return out


def _truthy(v) -> bool:
    return v is True or str(v).lower() in ("1", "true", "yes", "on")


def _file_hash(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def estimate(m: dict, seconds: float) -> dict | None:
    """按官方价格估算费用：识别按音频时长计费（unit 为 second / minute / hour）。"""
    p = m.get("price")
    if not p or "amount" not in p:
        return None
    per_sec = {"second": 1, "minute": 60, "hour": 3600}.get(p.get("unit"))
    if not per_sec:
        return None
    amount = p["amount"] * seconds / (per_sec * p.get("per", 1))
    sym = "¥" if p["currency"] == "CNY" else "$"
    return {"amount": round(amount, 6), "currency": p["currency"], "text": f"约 {sym}{amount:.4f}（{seconds / 60:.1f} 分钟）"}


# ---------- 识别 ----------
def transcribe(src: Path, request: dict, source: str = "cli", filename: str | None = None) -> dict:
    """识别一个音频 / 视频文件。src 是本机文件（HTTP 上传的先落到临时文件）。"""
    src = Path(src)
    if not src.exists() or not src.is_file():
        raise VoxError(f"找不到文件：{src}")
    req = normalize(request)
    m = catalog.find_model(req["model"])
    cid = hashlib.sha1((_file_hash(src) + json.dumps(req, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()[:16]
    out = DIR / f"{cid}.json"
    if out.exists() and request.get("cache") is not False:
        return {**json.loads(out.read_text()), "cached": True}
    eng = hub._engine(m)
    t = time.time()
    with tempfile.TemporaryDirectory(prefix="vox-stt-") as work:
        work = Path(work)
        try:
            if m["provider"] == "local":
                wav = work / "in.wav"
                dur = audio.to_wav16k(src, wav)
                with hub.SYNTH_LOCK:   # MLX 不是线程安全的：和合成共用一把锁
                    r = eng.transcribe(str(wav), req.get("language"), req.get("prompt"), req.get("hotwords"))
            else:
                dur = audio.duration(src)
                up = audio.for_upload(src, m["compat"].get("formats"), m["compat"].get("max_mb"), work)
                r = eng.transcribe(req, up)
        except providers.ProviderError as e:
            raise VoxError(f"{catalog.PROVIDERS[m['provider']]['name']}：{e}") from None
        except ValueError as e:
            raise VoxError(str(e)) from None
    segs = r.get("segments") or []
    words = r.get("words") or [w for s in segs for w in s.get("words", [])]
    rec = {"id": cid, "ts": time.time(), "source": source, "file": filename or src.name, "request": req,
           "text": r.get("text", ""), "language": r.get("language") or req.get("language"),
           "duration": round(float(r.get("duration") or dur or 0), 3),
           "segments": [{k: v for k, v in s.items() if k != "words"} for s in segs],
           "timed": bool(m["caps"].get("segments") or m["caps"].get("diarize")),   # segments 是否是真正的分句（能做字幕），而不只是分块
           "elapsed": round(time.time() - t, 2)}
    if req.get("words"):
        rec["words"] = words
    if m["provider"] != "local":
        rec["cost"] = estimate(m, rec["duration"])
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    tmp.replace(out)
    return rec


# ---------- 记录 ----------
def records(limit: int | None = None) -> list[dict]:
    """转写记录（新的在前），只带摘要；全文用 get。"""
    out = []
    for f in DIR.glob("*.json") if DIR.exists() else []:
        try:
            r = json.loads(f.read_text())
        except ValueError:
            continue
        out.append({k: r.get(k) for k in ("id", "ts", "source", "file", "request", "language", "duration", "elapsed", "cost", "timed")}
                   | {"preview": r.get("text", "")[:120], "speakers": len({s.get("speaker") for s in r.get("segments", []) if s.get("speaker")})})
    out.sort(key=lambda r: r["ts"] or 0, reverse=True)
    return out[:limit] if limit else out


def get(cid: str) -> dict:
    f = DIR / f"{cid}.json"
    if not (len(cid) == 16 and all(c in "0123456789abcdef" for c in cid)) or not f.exists():
        raise VoxError("找不到这条转写")
    return json.loads(f.read_text())


def delete(cid: str) -> dict:
    get(cid)
    (DIR / f"{cid}.json").unlink()
    return {"id": cid, "deleted": True}


# ---------- 输出格式 ----------
def _ts(sec: float, sep: str) -> str:
    ms = int(round(max(sec, 0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    mi, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{mi:02d}:{s:02d}{sep}{ms:03d}"


def _cues(rec: dict) -> list[dict]:
    if not rec.get("timed") or not rec.get("segments"):
        timed = [catalog.short(m) for m in catalog.MODELS if m["task"] == "stt" and (m["caps"].get("segments") or m["caps"].get("diarize"))]
        raise VoxError(f"这条转写没有分句时间戳（{rec['request']['model']} 只给整段文本），导不出字幕。"
                       f"要字幕请换带时间戳的模型：{', '.join(timed) or '（暂无）'}")
    return rec["segments"]


def _line(s: dict) -> str:
    return f"[{s['speaker']}] {s['text']}" if s.get("speaker") else s["text"]


def render(rec: dict, fmt: str = "txt") -> str:
    if fmt == "json":
        return json.dumps(rec, ensure_ascii=False, indent=1)
    if fmt == "txt":
        if any(s.get("speaker") for s in rec.get("segments", [])):   # 有说话人时按段落分行，便于阅读
            return "\n".join(_line(s) for s in rec["segments"]) + "\n"
        return rec.get("text", "") + "\n"
    if fmt == "srt":
        return "\n".join(f"{i}\n{_ts(s['start'], ',')} --> {_ts(s['end'], ',')}\n{_line(s)}\n" for i, s in enumerate(_cues(rec), 1))
    if fmt == "vtt":
        return "WEBVTT\n\n" + "\n".join(f"{_ts(s['start'], '.')} --> {_ts(s['end'], '.')}\n{_line(s)}\n" for s in _cues(rec))
    raise VoxError(f"不支持的格式 {fmt}，可选：{', '.join(FORMATS)}")
