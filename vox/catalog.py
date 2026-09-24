"""模型与音色目录：提供方（本地 / 云端）、模型规格、音色元数据。

统一命名（CLI、HTTP、WebUI 共用）：
  模型 ID    提供方/模型，如 local/qwen3、openai/gpt-4o-mini-tts；本地模型也接受短名 qwen3
  音色引用   模型短名:音色，如 qwen3:serena、kokoro:zf_003；自定义音色为 my:<id>
  请求参数   model / input / voice / instructions / speed / seed / lang / temperature / top_p / top_k / repetition_penalty
"""
from __future__ import annotations

import os

from .cloud_catalog import CLOUD_MODELS

# ---------- 提供方 ----------
# credentials：需要的环境变量（也可存进 ~/.config/vox/credentials.json）；icon 来自 LobeHub Icons（MIT），mono 表示单色图标
PROVIDERS = {
    "local": {"name": "本地", "kind": "local", "icon": "huggingface", "about": "在本机运行，模型下载后完全离线"},
    "openai": {"name": "OpenAI", "kind": "cloud", "icon": "openai", "mono": True, "region": "海外",
               "credentials": [{"env": "OPENAI_API_KEY", "label": "API Key"}], "optional": [{"env": "OPENAI_BASE_URL", "label": "Base URL（可选，接代理时填）"}],
               "console": "https://platform.openai.com/settings/organization/api-keys", "docs": "https://developers.openai.com/api/docs/guides/text-to-speech"},
    "inworld": {"name": "Inworld", "kind": "cloud", "icon": None, "letter": "In", "region": "海外",
                "credentials": [{"env": "INWORLD_API_KEY", "label": "API Key（控制台复制的完整 Base64 串）"}],
                "console": "https://platform.inworld.ai/api-keys", "docs": "https://docs.inworld.ai/tts/openai-compatibility"},
    "elevenlabs": {"name": "ElevenLabs", "kind": "cloud", "icon": "elevenlabs", "mono": True, "region": "海外",
                   "credentials": [{"env": "ELEVENLABS_API_KEY", "label": "API Key"}],
                   "console": "https://elevenlabs.io/app/settings/api-keys", "docs": "https://elevenlabs.io/docs/api-reference/text-to-speech/convert"},
    "gemini": {"name": "Google Gemini", "kind": "cloud", "icon": "gemini", "region": "海外",
               "credentials": [{"env": "GEMINI_API_KEY", "label": "API Key"}],
               "console": "https://aistudio.google.com/apikey", "docs": "https://ai.google.dev/gemini-api/docs/speech-generation"},
    "aliyun": {"name": "阿里云百炼", "kind": "cloud", "icon": "bailian", "region": "国内",
               "credentials": [{"env": "DASHSCOPE_API_KEY", "label": "API Key（北京地域）"}], "optional": [{"env": "DASHSCOPE_WORKSPACE_ID", "label": "WorkspaceId（可选，llm- 开头；填了走官方推荐的专属域名）"}],
               "console": "https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key", "docs": "https://help.aliyun.com/zh/model-studio/tts-model"},
    "volcengine": {"name": "火山引擎 豆包", "kind": "cloud", "icon": "doubao", "region": "国内",
                   "credentials": [{"env": "VOLC_TTS_API_KEY", "label": "API Key（新版控制台）"}],
                   "console": "https://console.volcengine.com/speech/new/setting/apikeys?projectName=default", "docs": "https://docs.volcengine.com/docs/6561/1598757"},
    "minimax": {"name": "MiniMax", "kind": "cloud", "icon": "minimax", "region": "国内",
                "credentials": [{"env": "MINIMAX_API_KEY", "label": "API Key"}], "optional": [{"env": "MINIMAX_BASE_URL", "label": "Base URL（国际站填 https://api.minimax.io）"}],
                "console": "https://platform.minimax.cn/user-center/basic-information/interface-key", "docs": "https://platform.minimaxi.com/docs/api-reference/speech-t2a-http"},
    "stepfun": {"name": "阶跃星辰", "kind": "cloud", "icon": "stepfun", "region": "国内",
                "credentials": [{"env": "STEPFUN_API_KEY", "label": "API Key"}], "optional": [{"env": "STEPFUN_BASE_URL", "label": "Base URL（国际站填 https://api.stepfun.ai/v1）"}],
                "console": "https://platform.stepfun.com/interface-key", "docs": "https://platform.stepfun.com/docs/zh/api-reference/audio/create-audio"},
    "siliconflow": {"name": "硅基流动", "kind": "cloud", "icon": "siliconcloud", "region": "国内",
                    "credentials": [{"env": "SILICONFLOW_API_KEY", "label": "API Key"}], "optional": [{"env": "SILICONFLOW_BASE_URL", "label": "Base URL（国际站填 https://api.siliconflow.com/v1）"}],
                    "console": "https://cloud.siliconflow.cn/account/ak", "docs": "https://docs.siliconflow.cn/cn/userguide/capabilities/text-to-speech"},
    "mimo": {"name": "小米 MiMo", "kind": "cloud", "icon": "xiaomimimo", "mono": True, "region": "国内",
             "credentials": [{"env": "MIMO_API_KEY", "label": "API Key（sk- 开头）"}],
             "console": "https://platform.xiaomimimo.com", "docs": "https://mimo.mi.com/docs/en-US/api/audio/tts"},
}

GEN = ("temperature", "top_p", "top_k", "repetition_penalty")

# ---------- 模型 ----------
# caps：voices 预置音色 / instructions 情绪指令 / design 用描述设计声音 / seed 可复现 / native_speed 原生语速
MODELS = [
    {"id": "local/qwen3", "alias": "qwen3", "provider": "local", "engine": "qwen3",
     "name": "Qwen3-TTS CustomVoice", "family": "Qwen3-TTS", "params_b": 1.7, "quant": "MLX 8bit", "size_gb": 3.08,
     "license": "Apache-2.0", "repo": os.environ.get("VOX_QWEN_MODEL", "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"),
     "homepage": "https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
     "languages": ["中文", "英语", "日语", "韩语", "德语", "法语", "俄语", "葡萄牙语", "西班牙语", "意大利语"],
     "caps": {"voices": True, "instructions": True, "design": False, "seed": True, "native_speed": False},
     "params": ["voice", "instructions", "speed", "lang", "seed", *GEN], "default_voice": "serena",
     "about": "9 个官方预置音色（含北京话、四川话），可用一句话控制语气和情绪。中文最自然。"},
    {"id": "local/qwen3-design", "alias": "qwen3-design", "provider": "local", "engine": "qwen3-design",
     "name": "Qwen3-TTS VoiceDesign", "family": "Qwen3-TTS", "params_b": 1.7, "quant": "MLX 8bit", "size_gb": 3.1,
     "license": "Apache-2.0", "repo": os.environ.get("VOX_QWEN_DESIGN_MODEL", "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit"),
     "homepage": "https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
     "languages": ["中文", "英语", "日语", "韩语", "德语", "法语", "俄语", "葡萄牙语", "西班牙语", "意大利语"],
     "caps": {"voices": False, "instructions": True, "design": True, "seed": True, "native_speed": False},
     "params": ["instructions", "speed", "lang", "seed", *GEN], "default_voice": None,
     "about": "没有预置音色：用一句话描述想要的声音（年龄、性别、音色、语气），模型现场设计。"},
    {"id": "local/kokoro", "alias": "kokoro", "provider": "local", "engine": "kokoro",
     "name": "Kokoro 82M 中文", "family": "Kokoro", "params_b": 0.082, "quant": "PyTorch", "size_gb": 0.33,
     "license": "Apache-2.0", "repo": os.environ.get("VOX_KOKORO_MODEL", "hexgrad/Kokoro-82M-v1.1-zh"),
     "homepage": "https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh",
     "languages": ["中文"],
     "caps": {"voices": True, "instructions": False, "design": False, "seed": False, "native_speed": True},
     "params": ["voice", "speed"], "default_voice": "zf_003",
     "about": "82M 小模型，CPU 就能跑，速度快；100 个中文音色，但语气偏平，英文单词容易读错。"},
] + CLOUD_MODELS  # 云端模型见 cloud_catalog.py

# ---------- 音色元数据 ----------
# Qwen3 预置音色：性别、母语、描述译自官方模型卡 https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
QWEN3_VOICES = [
    ("vivian", "Vivian", "女", "中文", "明亮、略带锋芒的年轻女声"),
    ("serena", "Serena", "女", "中文", "温暖柔和的年轻女声"),
    ("uncle_fu", "Uncle Fu", "男", "中文", "阅历感男声，音色低沉醇厚"),
    ("dylan", "Dylan", "男", "北京话", "清亮自然的北京青年男声"),
    ("eric", "Eric", "男", "四川话", "活泼的成都男声，明亮里带点沙哑"),
    ("ryan", "Ryan", "男", "英语", "节奏感强、有冲劲的男声"),
    ("aiden", "Aiden", "男", "英语", "阳光的美式男声，中频清晰"),
    ("ono_anna", "Ono Anna", "女", "日语", "俏皮轻盈的日语女声"),
    ("sohee", "Sohee", "女", "韩语", "温暖、情感丰富的韩语女声"),
]

# 声音设计的示例描述（WebUI 情绪 / 描述快捷项也用这里）
DESIGN_EXAMPLES = [
    "二十多岁的年轻女声，清亮活泼，普通话标准",
    "三十岁左右的男声，温和真诚，普通话标准",
    "四十岁左右的男声，低沉磁性，像纪录片旁白",
    "知性女声，语速平稳，播音腔",
    "元气满满的卡通角色声音，语速偏快",
    "沙哑的中年男声，懒洋洋的",
]
INSTRUCTION_EXAMPLES = ["平静自然地叙述", "沉稳温和的纪录片旁白", "轻快友好", "开心，带着笑意", "兴奋激动",
                        "心虚、小声、有点结巴", "无奈又好笑的吐槽", "惊讶", "严肃认真", "温柔安慰", "得意洋洋", "疲惫"]

DEFAULT_SAMPLE_TEXT = "你好，我是{name}。今天是 9 月 23 日，顺便读个英文词：GitHub。你觉得这个声音怎么样？"
SAMPLE_SEED = 20260923


def find_model(mid: str) -> dict | None:
    """接受完整 ID（local/qwen3）、短名（qwen3）或 OpenAI 风格的裸名。"""
    if not mid:
        return None
    for m in MODELS:
        if mid in (m["id"], m.get("alias")) or mid == m["id"].split("/", 1)[-1]:
            return m
    return None


def short(m: dict) -> str:
    return m.get("alias") or m["id"]
