"""云端适配器注册表：按目录里模型的 adapter 字段创建实例。新增 Provider：写一个 CloudEngine 子类，登记到 ADAPTERS。"""
from __future__ import annotations

from .base import CloudEngine, ProviderError  # noqa: F401
from .dashscope import DashScope
from .elevenlabs import ElevenLabs
from .gemini import Gemini
from .mimo import MiMo
from .minimax import MiniMax
from .openai_compat import OpenAICompat
from .volcengine import Volcengine

ADAPTERS = {"openai_compat": OpenAICompat, "elevenlabs": ElevenLabs, "gemini": Gemini, "mimo": MiMo,
            "dashscope": DashScope, "volcengine": Volcengine, "minimax": MiniMax}
_live: dict[str, CloudEngine] = {}


def engine_for(model: dict) -> CloudEngine:
    if model["id"] not in _live:
        _live[model["id"]] = ADAPTERS[model["adapter"]](model)
    return _live[model["id"]]
