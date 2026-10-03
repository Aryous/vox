"""本地引擎。按模型实例化（get(模型字典)），同一类引擎可以跑不同的仓库（尺寸、量化）；新增引擎写一个类，登记到 ENGINES。

合成（tts）引擎实现 synth(text, voice, instruct, speed, lang, seed, **采样参数) -> (float32 音频, 采样率)，以及 voices() / languages()。
识别（stt）引擎实现 transcribe(wav 路径, language, prompt, hotwords, duration) -> dict（text / language / segments），见 MlxSTT。
引擎的 spec 是它对应的模型条目（注册表字段），引擎按其中的模型专属配置调用（如 prompt_format、tokens_per_sec）。
所有引擎都有 is_ready()（文件是否在本地）、is_loaded()（是否在内存里）、local_path()。
"""
from __future__ import annotations

import contextlib
import json
import re
import sys
import warnings
from pathlib import Path

import numpy as np

from . import paths

warnings.filterwarnings("ignore")


class Engine:
    name = ""
    model = ""
    about = ""
    native_speed = False  # 不支持原生语速的引擎，由 cli 用 ffmpeg atempo 变速（音高不变）
    params: tuple[str, ...] = ("voice", "speed")
    default_voice = None
    spec: dict = {}       # 模型条目，get() 时填入

    def voices(self) -> list[str]:
        raise NotImplementedError

    def languages(self) -> list[str]:
        return ["chinese"]

    def is_ready(self) -> bool:
        return True

    def synth(self, text, voice=None, instruct=None, speed=1.0, lang="chinese", seed=None, **gen):
        raise NotImplementedError

    def is_loaded(self) -> bool:
        return False

    def info(self) -> dict:
        return {"name": self.name, "model": self.model, "about": self.about, "params": list(self.params),
                "ready": self.is_ready(), "default_voice": self.default_voice, "native_speed": self.native_speed}


class Kokoro(Engine):
    name = "kokoro"
    model = "hexgrad/Kokoro-82M-v1.1-zh"
    about = "82M，Apache 2.0，CPU 即可，100 个中文音色（zf_ 女 / zm_ 男）；快但语气平，英文词容易读错"
    native_speed = True
    default_voice = "zf_003"

    def __init__(self, repo=None):
        self.model = repo or self.model
        self._zh = None

    def local_path(self):
        return Path.home() / ".cache" / "huggingface" / "hub" / ("models--" + self.model.replace("/", "--"))

    def is_loaded(self):
        return self._zh is not None

    def is_ready(self):
        snap = self.local_path() / "snapshots"
        return any(snap.glob("*/*.pth")) if snap.exists() else False

    def _load(self):
        if self._zh:
            return
        from kokoro import KModel, KPipeline

        en = KPipeline(lang_code="a", repo_id=self.model, model=False)

        def en_cb(t):
            try:
                return next(en(t)).phonemes
            except Exception:
                return ""

        self._zh = KPipeline(lang_code="z", repo_id=self.model, model=KModel(repo_id=self.model).eval(), en_callable=en_cb)

    def voices(self):
        cache = paths.KOKORO_VOICES  # 音色清单只需联网取一次
        if cache.exists():
            return json.loads(cache.read_text())
        from huggingface_hub import list_repo_files

        vs = sorted(f[7:-3] for f in list_repo_files(self.model) if f.startswith("voices/z"))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(vs))
        return vs

    def synth(self, text, voice=None, instruct=None, speed=1.0, lang="chinese", seed=None, **gen):
        self._load()
        wav = np.concatenate([r.audio.numpy() for r in self._zh(text, voice=voice or self.default_voice, speed=speed)])
        return wav.astype(np.float32), 24000


class _MlxRepo(Engine):
    """用 vox 下载的 MLX 仓库（~/.vox/models/<repo>，见 fetch.py）或本机路径运行的引擎：合成和识别共用。"""

    def __init__(self, repo=None):
        self.model = repo or self.model
        self._m = None

    def local_path(self):
        from . import fetch

        return Path(self.model) if Path(self.model).exists() else fetch.local_dir(self.model)

    def _src(self):
        from . import fetch

        if Path(self.model).exists():
            return self.model
        return str(fetch.local_dir(self.model)) if fetch.is_ready(self.model) else None

    def is_ready(self):
        return self._src() is not None

    def is_loaded(self):
        return self._m is not None

    def _loader(self):
        raise NotImplementedError

    def _load(self):
        if not self._m:
            src = self._src()
            if not src:
                raise SystemExit(f"模型未下载：先运行 vox models add {self.model}（走 ModelScope 并按 HuggingFace 哈希校验）")
            with contextlib.redirect_stdout(sys.stderr):  # 库在加载时会往 stdout 打日志
                self._m = self._loader()(src)
        return self._m


class _Qwen3(_MlxRepo):
    native_speed = False

    def _loader(self):
        from mlx_audio.tts.utils import load_model

        return load_model

    def languages(self):
        return self._load().get_supported_languages()

    @staticmethod
    def _collect(results):
        return np.concatenate([np.array(r.audio, dtype=np.float32).reshape(-1) for r in results])

    @staticmethod
    def _gen(gen):  # 只透传模型认识的采样参数
        keys = ("temperature", "top_p", "top_k", "repetition_penalty")
        return {k: (int(v) if k == "top_k" else float(v)) for k, v in gen.items() if k in keys and v not in (None, "")}

    def _seed(self, seed):
        if seed not in (None, ""):
            import mlx.core as mx

            mx.random.seed(int(seed))


QWEN_GEN = ("temperature", "top_p", "top_k", "repetition_penalty")


class Qwen3(_Qwen3):
    name = "qwen3"
    model = "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"
    about = "Qwen3-TTS CustomVoice 1.7B（MLX 8bit），Apache 2.0；9 个预置音色 + instruct 控制语气情绪"
    params = ("voice", "instruct", "speed", "lang", "seed") + QWEN_GEN
    default_voice = "vivian"

    def voices(self):
        m = self._load()
        return sorted(m.get_supported_speakers()) if hasattr(m, "get_supported_speakers") else sorted((m.config.spk_id or {}).keys())

    def synth(self, text, voice=None, instruct=None, speed=1.0, lang="chinese", seed=None, **gen):
        m = self._load()
        self._seed(seed)
        wav = self._collect(m.generate_custom_voice(text=text, speaker=voice or self.default_voice, language=lang,
                                                    instruct=instruct or None, **self._gen(gen)))
        return wav, m.sample_rate


class Qwen3Design(_Qwen3):
    name = "qwen3-design"
    model = "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit"
    about = "Qwen3-TTS VoiceDesign 1.7B（MLX 8bit）；不用预置音色，用 instruct 一句话描述想要的声音"
    params = ("instruct", "speed", "lang", "seed") + QWEN_GEN

    def voices(self):
        return []

    def synth(self, text, voice=None, instruct=None, speed=1.0, lang="chinese", seed=None, **gen):
        desc = instruct or voice
        if not desc:
            raise SystemExit("qwen3-design 需要用 -i 描述声音")
        m = self._load()
        self._seed(seed)
        return self._collect(m.generate_voice_design(text=text, instruct=desc, language=lang, **self._gen(gen))), m.sample_rate


class MlxSTT(_MlxRepo):
    """mlx-audio 的语音识别：同一个接口跑 Qwen3-ASR、SenseVoice、Fun-ASR、Whisper、Parakeet……（按仓库里的 config 自动选实现）。
    换模型只需要在注册表里换 repo。输入是 16 kHz 单声道 wav（stt.py 用 ffmpeg 先转好）。"""
    name = "mlx-stt"
    model = "mlx-community/Qwen3-ASR-0.6B-8bit"
    params = ("language", "prompt", "hotwords")

    def voices(self):
        return []

    def _loader(self):
        from mlx_audio.stt.utils import load_model

        return load_model

    def transcribe(self, wav: str, language: str | None = None, prompt: str | None = None, hotwords: list[str] | None = None,
                   duration: float | None = None) -> dict:
        import inspect

        m = self._load()
        accepts = inspect.signature(m.generate).parameters
        kw = {}
        if language and "language" in accepts:
            kw["language"] = language
        fmt = self.spec.get("prompt_format")
        if fmt:   # 模型要求特定的指令写法：热词按它的格式接在指令后面，不走库的通用拼法（会把默认指令整个换掉）
            prompt = fmt["base"] + (fmt["hotwords"].format(", ".join(hotwords)) if hotwords else "")
        elif hotwords and "hotwords" in accepts:
            kw["hotwords"] = hotwords
        if prompt:
            for k in ("system_prompt", "initial_prompt", "prompt"):   # 各实现的叫法不一
                if k in accepts:
                    kw[k] = prompt
                    break
        tps = self.spec.get("tokens_per_sec")
        if tps and duration and "max_tokens" in accepts:
            kw["max_tokens"] = int(duration * tps) + 1024
        with contextlib.redirect_stdout(sys.stderr):
            r = m.generate(wav, **kw)
        lang = r.language[0] if isinstance(r.language, list) and r.language else r.language
        segs = [self._seg(x) for x in (r.segments or []) if isinstance(x, dict)]
        text = (r.text or "").strip()
        if any("speaker" in x for x in segs):   # 带说话人的模型，原文里夹着 [12.3][S01] 这样的标记：改用分好的段，一段一行
            text = "\n".join(x["text"] for x in segs)
        return {"text": text, "language": lang if isinstance(lang, str) else None, "segments": segs}

    @staticmethod
    def _seg(x: dict) -> dict:
        spk = x.get("speaker_id") or x.get("speaker")
        text = str(x.get("text", "")).strip()
        if spk:
            text = re.sub(rf"^\[{re.escape(str(spk))}\]\s*", "", text)
        return {"start": float(x.get("start", 0)), "end": float(x.get("end", 0)), "text": text,
                **({"speaker": str(spk)} if spk not in (None, "") else {}),
                **({"words": [{"start": float(w["start"]), "end": float(w["end"]), "word": w.get("word", "")} for w in x["words"]]} if x.get("words") else {})}


ENGINES = {e.name: e for e in (Qwen3, Qwen3Design, Kokoro, MlxSTT)}
_live: dict[str, Engine] = {}   # 模型 ID → 引擎实例


def loaded() -> list[str]:
    """已加载进内存的模型 ID。"""
    return [mid for mid, e in _live.items() if e.is_loaded()]


def unload(mid: str) -> bool:
    """释放模型占用的内存。"""
    e = _live.pop(mid, None)
    if not e:
        return False
    del e
    import gc

    gc.collect()
    try:
        import mlx.core as mx

        mx.clear_cache()
    except Exception:
        pass
    return True


def get(m: dict) -> Engine:
    """按模型字典取引擎实例（engine 字段选类，repo 字段选仓库）。"""
    name = m["engine"]
    if name not in ENGINES:
        raise SystemExit(f"未知引擎 {name}，可选：{', '.join(ENGINES)}")
    e = _live.get(m["id"])
    if e is None or e.model != (m.get("repo") or ENGINES[name].model):
        e = _live[m["id"]] = ENGINES[name](m.get("repo"))
    e.spec = m
    return e
