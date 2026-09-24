"""TTS 引擎。每个引擎实现 synth(text, voice, instruct, speed, lang, seed, **采样参数) -> (float32 音频, 采样率)，
以及 voices() / languages() / is_ready()。类属性 params 声明它支持哪些可调参数，WebUI 据此显示控件。

新增引擎：写一个类，登记到 ENGINES。
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
CACHE = Path(os.environ.get("VOX_HOME", Path.home() / ".cache" / "vox"))


class Engine:
    name = ""
    model = ""
    about = ""
    native_speed = False  # 不支持原生语速的引擎，由 cli 用 ffmpeg atempo 变速（音高不变）
    params: tuple[str, ...] = ("voice", "speed")
    default_voice = None

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
    model = os.environ.get("VOX_KOKORO_MODEL", "hexgrad/Kokoro-82M-v1.1-zh")
    about = "82M，Apache 2.0，CPU 即可，100 个中文音色（zf_ 女 / zm_ 男）；快但语气平，英文词容易读错"
    native_speed = True
    default_voice = "zf_003"

    def __init__(self):
        self._zh = None

    def is_loaded(self):
        return self._zh is not None

    def is_ready(self):
        snap = Path.home() / ".cache" / "huggingface" / "hub" / ("models--" + self.model.replace("/", "--")) / "snapshots"
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
        cache = CACHE / "kokoro-voices.json"  # 音色清单只需联网取一次
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


class _Qwen3(Engine):
    native_speed = False

    def __init__(self):
        self._m = None

    def _src(self):
        from . import fetch

        if Path(self.model).exists():
            return self.model
        return str(fetch.local_dir(self.model)) if fetch.is_ready(self.model) else None

    def is_ready(self):
        return self._src() is not None

    def is_loaded(self):
        return self._m is not None

    def _load(self):
        if not self._m:
            src = self._src()
            if not src:
                raise SystemExit(f"模型未下载：先运行 vox fetch {self.name}（约 3 GB，走 ModelScope 并校验哈希）")
            from mlx_audio.tts.utils import load_model

            with contextlib.redirect_stdout(sys.stderr):  # 库在加载时会往 stdout 打日志
                self._m = load_model(src)
        return self._m

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
    model = os.environ.get("VOX_QWEN_MODEL", "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit")
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
    model = os.environ.get("VOX_QWEN_DESIGN_MODEL", "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit")
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


ENGINES = {e.name: e for e in (Qwen3, Qwen3Design, Kokoro)}
_live: dict[str, Engine] = {}


def loaded() -> list[str]:
    return [n for n, e in _live.items() if e.is_loaded()]


def unload(name: str) -> bool:
    """释放模型占用的内存。"""
    e = _live.pop(name, None)
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


def get(name: str) -> Engine:
    if name not in ENGINES:
        raise SystemExit(f"未知引擎 {name}，可选：{', '.join(ENGINES)}")
    if name not in _live:
        _live[name] = ENGINES[name]()
    return _live[name]
