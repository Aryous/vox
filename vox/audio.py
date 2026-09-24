"""音频写出与格式转换（ffmpeg）。"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

FORMATS = {"wav": "audio/wav", "mp3": "audio/mpeg", "flac": "audio/flac", "opus": "audio/ogg", "aac": "audio/aac", "pcm": "audio/L16"}


def _ff():
    if not shutil.which("ffmpeg"):
        raise SystemExit("需要 ffmpeg：brew install ffmpeg")


def duration(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def write_wav(wav, sr, out: Path, speed=1.0, native_speed=True) -> float:
    """写 wav；引擎不支持原生语速时用 atempo 变速（音高不变）。返回时长秒。"""
    import soundfile as sf

    out.parent.mkdir(parents=True, exist_ok=True)
    if speed == 1.0 or native_speed:
        sf.write(out, wav, sr)
        return len(wav) / sr
    _ff()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = Path(f.name)
    sf.write(tmp, wav, sr)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-filter:a", f"atempo={speed}", str(out)], check=True)
    tmp.unlink()
    return duration(out)


def convert(src: Path, fmt: str) -> Path:
    """把 wav 转成指定格式，结果缓存在同目录。"""
    if fmt == "wav":
        return src
    if fmt not in FORMATS:
        raise ValueError(f"不支持的格式 {fmt}，可选：{', '.join(FORMATS)}")
    out = src.with_suffix("." + ("raw" if fmt == "pcm" else "ogg" if fmt == "opus" else fmt))
    if out.exists():
        return out
    _ff()
    args = {"mp3": ["-b:a", "128k"], "opus": ["-c:a", "libopus"], "aac": ["-c:a", "aac"], "flac": [],
            "pcm": ["-f", "s16le", "-acodec", "pcm_s16le"]}[fmt]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), *args, str(out)], check=True)
    return out


def bytes_to_wav(data: bytes, fmt: str, out: Path, speed=1.0, native_speed=True) -> float:
    """云端返回的音频（mp3 / wav / 无头 PCM 如 s16le:24000:1）统一转成 wav；需要时用 atempo 变速。"""
    _ff()
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = fmt.startswith("s16le")
    with tempfile.NamedTemporaryFile(suffix=".raw" if raw else "." + fmt, delete=False) as f:
        f.write(data)
        tmp = Path(f.name)
    src = ["-f", "s16le", "-ar", fmt.split(":")[1], "-ac", fmt.split(":")[2]] if raw else []
    filt = ["-filter:a", f"atempo={speed}"] if speed != 1.0 and not native_speed else []
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *src, "-i", str(tmp), *filt, str(out)], capture_output=True, text=True)
    tmp.unlink()
    if r.returncode:
        raise ValueError(f"音频解码失败（{fmt}）：{r.stderr.strip()[:200]}")
    return duration(out)
