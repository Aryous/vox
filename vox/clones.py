"""克隆音色：用一段录音得到一个可以反复使用的声音（clone:<id>）。

音色有三种来源，引用写法各不相同：
  预置音色   模型或厂商自带的说话人             qwen3:serena
  预设       音色 + 语气 + 语速 + 种子的组合      preset:<id>（旧写法 my:<id> 仍然认）
  克隆音色   从一段录音得到的说话人             clone:<id>

一个克隆音色 = 一段参考录音 + 它的文字稿，存在 ~/.vox/clones/<id>/：
  sample.wav    规范化后的参考录音（24 kHz 单声道，去掉首尾静音，最长 MAX_SEC 秒）
  consent.wav   同意声明录音（可选；Gemini 等要求本人朗读一段规定的话）
  clone.json    id / name / text（文字稿）/ text_auto（文字稿是否自动识别）/ lang / file（原文件名）/ duration
                / rev / created / remote（在各家云端注册后的音色 ID）
任何支持克隆（caps.clone）的模型都能用它：
  本地模型    每次合成都带上参考录音（零样本，不需要训练）
  云端模型    compat.clone.mode = "voice"：第一次用时上传给这家，记下对方返回的音色 ID，之后复用
              compat.clone.mode = "inline"：每次请求都带上参考录音
rev 是录音和文字稿的哈希：换了录音或改了文字稿，合成缓存和云端注册都会自动失效、重新来过。
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import audio, catalog, paths

DIR = paths.CLONES
MIN_SEC, MAX_SEC = 3.0, 30.0
PREFIX = "clone:"


class CloneError(ValueError):
    pass


# ---------- 存取 ----------
def _dir(cid: str) -> Path:
    if not re.fullmatch(r"[\w一-鿿-]{1,64}", cid or ""):
        raise CloneError(f"没有克隆音色 {PREFIX}{cid}")
    return DIR / cid


def records() -> list[dict]:
    out = []
    for f in sorted(DIR.glob("*/clone.json")) if DIR.exists() else []:
        try:
            out.append(json.loads(f.read_text()))
        except ValueError:
            continue
    out.sort(key=lambda r: r.get("created", 0), reverse=True)
    return out


def get(cid: str) -> dict:
    f = _dir(cid) / "clone.json"
    if not f.exists():
        raise CloneError(f"没有克隆音色 {PREFIX}{cid}（vox clones 查看已有的）")
    return json.loads(f.read_text())


def _write(rec: dict):
    d = _dir(rec["id"])
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "clone.tmp"
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    tmp.replace(d / "clone.json")


def sample_path(rec: dict) -> Path:
    return _dir(rec["id"]) / "sample.wav"


def consent_path(rec: dict) -> Path | None:
    p = _dir(rec["id"]) / "consent.wav"
    return p if p.exists() else None


def is_ref(v) -> bool:
    return isinstance(v, str) and v.startswith(PREFIX)


def from_ref(ref: str) -> dict:
    return get(ref[len(PREFIX):])


def _rev(wav: Path, text: str) -> str:
    return hashlib.sha1(wav.read_bytes() + text.encode()).hexdigest()[:12]


# ---------- 创建 ----------
def _normalize(src: Path, out: Path) -> float:
    """任意音视频 → 24 kHz 单声道 wav：去掉首尾静音，最长 MAX_SEC 秒。"""
    audio._ff()
    trim = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.2"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "24000",
                        "-af", f"{trim},areverse,{trim},areverse", "-t", str(MAX_SEC), str(out)], capture_output=True, text=True)
    if r.returncode:
        raise CloneError(f"读不了这个文件（{src.name}）：{r.stderr.strip()[:200]}")
    return audio.duration(out)


def _transcribe(wav: Path, lang: str | None) -> str:
    """用本地识别模型自动生成文字稿；没有本地识别模型时返回空（部分模型没有文字稿也能克隆，只是像得少一些）。"""
    from . import stt

    m = stt.local_model()
    if not m:
        return ""
    return stt.transcribe(wav, {"model": m["id"], **({"language": lang} if lang else {})}, source="clone", record=False)["text"].strip()


def create(src: Path, name: str, text: str | None = None, lang: str | None = None, consent: Path | None = None,
           filename: str | None = None, cid: str | None = None) -> dict:
    """从一段录音新建（或用同一个 id 覆盖）克隆音色。text 不给时用本地识别模型自动生成。"""
    src = Path(src)
    if not src.is_file():
        raise CloneError(f"找不到文件：{src}")
    name = (name or "").strip() or (filename or src.name).rsplit(".", 1)[0]
    cid = cid or re.sub(r"[^\w一-鿿-]+", "-", name).strip("-").lower()[:40] or f"c{int(time.time())}"
    d = _dir(cid)
    d.mkdir(parents=True, exist_ok=True)
    wav = d / "sample.wav"
    dur = _normalize(src, wav.with_suffix(".tmp.wav"))
    if dur < MIN_SEC:
        wav.with_suffix(".tmp.wav").unlink(missing_ok=True)
        raise CloneError(f"有效录音只有 {dur:.1f} 秒，至少要 {MIN_SEC:.0f} 秒（建议 10–20 秒、一个人、没有背景音乐）")
    wav.with_suffix(".tmp.wav").replace(wav)
    if consent:
        _normalize(Path(consent), d / "consent.wav")
    auto = text is None or not str(text).strip()
    text = _transcribe(wav, lang) if auto else str(text).strip()
    old = {}
    try:
        old = get(cid)
    except CloneError:
        pass
    rec = {"id": cid, "name": name, "text": text, "text_auto": auto and bool(text), "lang": lang or old.get("lang"),
           "consent": bool(consent) or (d / "consent.wav").exists(),
           "file": filename or src.name, "duration": round(dur, 2), "rev": _rev(wav, text),
           "created": old.get("created", time.time()), "updated": time.time(), "remote": old.get("remote", {})}
    _write(rec)
    return rec


def update(cid: str, name: str | None = None, text: str | None = None, consent: Path | None = None) -> dict:
    """改名、改文字稿、补交同意声明录音。同意声明不影响 rev：它只是给要求它的云端看的，不改变声音本身。"""
    rec = get(cid)
    if consent:
        _normalize(Path(consent), _dir(cid) / "consent.wav")
        rec["consent"] = True
    if name is not None and name.strip():
        rec["name"] = name.strip()
    if text is not None:
        rec["text"], rec["text_auto"] = text.strip(), False
        rec["rev"] = _rev(sample_path(rec), rec["text"])   # 文字稿变了：云端注册失效，下次用时重新上传
    _write(rec)
    return rec


def delete(cid: str, remote_cleanup=None) -> dict:
    """删除克隆音色。remote_cleanup(model_id, remote) 用来顺带删掉云端注册的音色（失败不影响本地删除）。"""
    rec = get(cid)
    failed = []
    for key, r in (rec.get("remote") or {}).items():
        if remote_cleanup:
            try:
                remote_cleanup(key, r)
            except Exception as e:   # 云端删不掉（Key 失效、已过期）不阻止本地删除，但要告诉用户
                failed.append(f"{key}：{e}")
    shutil.rmtree(_dir(cid))
    return {"id": cid, "deleted": True, "remote_failed": failed}


# ---------- 云端注册 ----------
def remote_key(m: dict) -> str:
    """云端音色 ID 的作用范围：多数厂商同一账号下各模型共用（按 Provider 记），少数按模型（compat.clone.per_model）。"""
    return m["id"] if m["compat"].get("clone", {}).get("per_model") else m["provider"]


def remote(rec: dict, m: dict) -> dict | None:
    """这条克隆音色在这家云端的注册记录；录音或文字稿改过（rev 不同）就视为没有。"""
    r = (rec.get("remote") or {}).get(remote_key(m))
    return r if r and r.get("rev") == rec["rev"] and not _expired(r) else None


def _expired(r: dict) -> bool:
    return bool(r.get("expires")) and r["expires"] < time.time()


def save_remote(rec: dict, m: dict, info: dict) -> dict:
    rec = get(rec["id"])   # 重新读，避免覆盖并发写入
    rec.setdefault("remote", {})[remote_key(m)] = {**info, "rev": rec["rev"], "model": m["id"], "created": time.time()}
    _write(rec)
    return rec


def models_for(task_ok=lambda m: True) -> list[dict]:
    return [m for m in catalog.MODELS if m["task"] == "tts" and m["caps"].get("clone") and task_ok(m)]
