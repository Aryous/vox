"""模型目录：从注册表数据、在线列表和用户添加的条目，组装出 vox 认识的全部模型。

两类任务（模型的 task 字段）：
  tts   语音合成：文字 → 声音（vox say / POST /v1/audio/speech）
  stt   语音识别：声音 → 文字（vox transcribe / POST /v1/audio/transcriptions）
  两类模型共用同一套 Provider、凭证、「我的模型」、下载与加载；各自的能力（caps）和参数（params）不同。

统一命名（CLI、HTTP、WebUI 共用）：
  模型 ID    提供方/模型，如 local/qwen3、openai/gpt-4o-mini-tts、local/qwen3-asr；本地模型也接受短名 qwen3
  音色引用   模型短名:音色，如 qwen3:serena、kokoro:zf_003；自定义音色为 my:<id>
  请求参数   model / input / voice / instructions / speed / seed / lang / temperature / top_p / top_k / repetition_penalty

数据与代码分开：
  代码（vox/providers/*.py、vox/engines.py）只负责「怎么调用」：每家的请求怎么拼、响应怎么解析。
  数据（vox/registry.json）负责「有什么」：Provider 的连接方式、适配器配置、已核对的模型元数据（能力、价格、音色）。
  注册表随包发布，也可以用 vox models update 拉新版（存在缓存目录，日期更新时优先生效）。

模型条目的三种来源（source 字段）：
  registry     注册表里核对过的模型
  discovered   各 Provider 在线列表查到的模型（缓存在 <缓存目录>/discovered/<provider>.json）
  custom       用户手动添加的模型 ID（记在 ~/.vox/models.json）
文件位置见 paths.py。
在线查到、但注册表里没有的模型，借用 template 指向的同家模型的配置（请求格式相同），能力标记为 inferred（推断）。

注册表字段：
  providers.<id>   name / kind（local|cloud）/ icon / region / credentials / optional / console / docs
                   adapter / key_env / compat（适配器配置）/ model_defaults（该家模型的公共字段）/ discover（在线列表怎么查）
  models[]         provider / remote（Provider 那边的模型 ID）/ name / caps / params / price / voices（"@音色集" 或列表）
                   recommended（连接后默认加进「我的模型」）/ about / languages …
  stt_models[]     语音识别模型，字段同上（没有音色）。单独成表：旧版 vox 拉到新注册表时只认 models，不会把识别模型当成合成模型
  providers.<id>.stt   这家语音识别的配置：adapter / compat / model_defaults（缺省沿用这家的合成配置）
  voice_sets       可复用的静态音色表

自定义 Provider（~/.vox/providers.json）：用户自己加的服务，比如本机的 Kokoro-FastAPI、代理、新厂商。
只存最少的配置（类型、地址、要不要 Key、几个兼容选项），在这里展开成和注册表一样的 Provider。
  price            {"amount", "currency", "per", "unit"}；unit 为 char / byte（UTF-8 字节）/ cjk2（汉字按 2 字符）/ token（只展示）
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from . import paths

BUILTIN = Path(__file__).with_name("registry.json")
UPDATED = paths.REGISTRY_UPDATE         # vox models update 拉到的新版注册表
DISCOVERED = paths.DISCOVERED           # 在线列表缓存
PREFS = paths.MY_MODELS                 # 用户的模型清单：我的模型、手动添加

GEN = ("temperature", "top_p", "top_k", "repetition_penalty")
TASKS = ("tts", "stt")
CONNECTION = ("base", "base_env", "auth")   # 两类任务共用的连接配置
BASE_CAPS = {"voices": True, "instructions": False, "design": False, "seed": False, "native_speed": True}
# 识别模型的能力：segments 分句时间戳（能做字幕）/ words 逐词时间戳 / diarize 区分说话人 / detect 自动识别语种 / prompt 上下文提示 / hotwords 热词
STT_CAPS = {"segments": False, "words": False, "diarize": False, "detect": True, "prompt": False, "hotwords": False}
TEMPLATE_DROP = ("id", "alias", "name", "recommended", "price", "homepage", "about", "repo_env", "instr_examples", "source", "inferred")

REG: dict = {}
PROVIDERS: dict = {}
VOICE_SETS: dict = {}
MODELS: list[dict] = []   # 原地重建，其他模块持有的引用始终有效
_BY_ID: dict = {}


def _read(p: Path, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def valid(reg) -> bool:
    return isinstance(reg, dict) and reg.get("schema") == 1 and isinstance(reg.get("providers"), dict) and isinstance(reg.get("models"), list)


def load_registry() -> dict:
    """内置注册表与 vox models update 拉到的版本，取日期较新的一个。"""
    reg = json.loads(BUILTIN.read_text())
    reg["_from"] = "builtin"
    up = _read(UPDATED, None)
    if valid(up) and str(up.get("updated", "")) > str(reg.get("updated", "")):
        up["_from"] = "updated"
        return up
    return reg


def voice_list(ref) -> list[dict] | str:
    """解析音色字段："@集合名"、集合与字典混排的列表、字符串列表（在线列表常见），或 "engine"（由本地引擎提供）。"""
    if ref in (None, "engine"):
        return ref or []
    if isinstance(ref, str):
        return copy.deepcopy(VOICE_SETS.get(ref[1:], [])) if ref.startswith("@") else []
    out = []
    for x in ref:
        if isinstance(x, str) and x.startswith("@"):
            out += copy.deepcopy(VOICE_SETS.get(x[1:], []))
        elif isinstance(x, str):
            out.append({"voice": x, "name": x, "gender": "", "lang": "", "description": ""})
        elif isinstance(x, dict) and x.get("voice"):
            out.append({"name": x["voice"], "gender": "", "lang": "", "description": "", **x})
    return out


def task_view(p: dict, task: str) -> dict:
    """Provider 在某个任务下的配置：识别任务用 p["stt"] 里的覆盖项，其余沿用这家的合成配置（同一个 Key、同一个地址）。"""
    if task != "stt":
        return p
    st = p.get("stt") or {}
    conn = {k: v for k, v in p.get("compat", {}).items() if k in CONNECTION}   # 只继承连接方式，合成专用的参数（音色前缀、采样率……）不带过来
    return {**p, "adapter": st.get("adapter", p.get("adapter")), "compat": {**conn, **st.get("compat", {})},
            "model_defaults": st.get("model_defaults", {}), "discover": st.get("discover")}


def materialize(entry: dict, source: str, templates: dict | None = None) -> dict | None:
    """把注册表 / 在线列表 / 用户添加的条目补全成完整的模型字典。Provider 未知或没有可用的适配器时返回 None。"""
    pid = entry.get("provider")
    task = entry.get("task", "tts")
    p = task_view(PROVIDERS.get(pid) or {}, task) if PROVIDERS.get(pid) else None
    if not p or task not in TASKS:
        return None
    tpl = (templates or {}).get(entry.get("template")) if entry.get("template") else None
    if tpl:
        base = {k: v for k, v in copy.deepcopy(tpl).items() if k not in TEMPLATE_DROP}
        caps = dict(tpl["caps"])
    else:
        base = copy.deepcopy(p.get("model_defaults", {}))
        caps = {**(STT_CAPS if task == "stt" else BASE_CAPS), **base.pop("caps", {})}
    m = {**base, **{k: v for k, v in copy.deepcopy(entry).items() if k != "template"}, "task": task}
    m["caps"] = {**caps, **entry.get("caps", {})}
    m.setdefault("languages", ["多语言"])
    if p["kind"] == "cloud":
        m.setdefault("adapter", p.get("adapter"))
        m.setdefault("key_env", p.get("key_env"))
        m["compat"] = {**p.get("compat", {}), **(tpl or {}).get("compat", {}), **entry.get("compat", {})}
        m.setdefault("license", "商用 API")
        if not m.get("remote"):
            return None
        m.setdefault("id", f"{pid}/{m['remote']}")
    else:
        if m.get("repo_env") and os.environ.get(m["repo_env"]):
            m["repo"] = os.environ[m["repo_env"]]
        if not m.get("id"):
            return None
    m.setdefault("name", m.get("remote") or m["id"].split("/", 1)[-1])
    if task == "stt":   # 识别模型没有音色
        m["voices"], m["default_voice"] = [], None
        m["caps"]["voices"] = False
        m.setdefault("params", ["language"] + [k for k in ("prompt", "hotwords") if m["caps"].get(k)])
    else:
        m["voices"] = voice_list(m.get("voices"))
        if m["voices"] != "engine":
            m.setdefault("default_voice", (m["voices"][0]["voice"] if m["voices"] else None))
    m["source"] = source
    m["inferred"] = False if p.get("custom") else entry.get("inferred", bool(entry.get("template")) and not entry.get("caps"))   # 自定义 Provider 的能力是用户声明的
    return m


# 自定义 Provider 的类型：目前是 OpenAI 兼容（POST {base}/audio/speech），覆盖自建服务、代理和多数新厂商
PROVIDER_TYPES = {"openai": {"label": "OpenAI 兼容", "adapter": "openai_compat"}}
INSTRUCTION_MODES = {"instructions": "instructions 字段（OpenAI 写法）", "instruction": "instruction 字段", "prefix": "写进正文（指令<|endofprompt|>正文）", "none": "不支持"}


def key_env_for(pid: str) -> str:
    return "VOX_" + "".join(c if c.isalnum() else "_" for c in pid.upper()) + "_API_KEY"


def _letter(name: str) -> str:
    """字母图标：中文取一个字，英文取两个字母。"""
    name = name.strip() or "?"
    return name[0] if ord(name[0]) > 0x2E80 else (name[:2].title() if len(name) > 1 else name.upper())


def custom_provider(pid: str, cfg: dict) -> dict:
    """把自定义 Provider 的配置展开成完整的 Provider（和注册表里的同一结构）。"""
    t = PROVIDER_TYPES.get(cfg.get("type", "openai"), PROVIDER_TYPES["openai"])
    base = cfg["base_url"].rstrip("/")
    needs_key = cfg.get("auth", True)
    env = key_env_for(pid) if needs_key else None
    mode = cfg.get("instructions", "instructions")
    voices = [v.strip() for v in cfg.get("voices", []) if str(v).strip()]
    caps = {"voices": bool(voices) or cfg.get("fetch_voices", True), "instructions": mode != "none", "design": False, "seed": False,
            "native_speed": cfg.get("native_speed", True)}
    params = [k for k, on in (("voice", caps["voices"]), ("instructions", caps["instructions"]), ("speed", True)) if on]
    compat = {"base": base, "instructions": None if mode == "none" else mode, "speed": [0.25, 4] if caps["native_speed"] else None}
    if cfg.get("fetch_voices", True):
        compat["list_voices"] = {"url": "{base}/audio/voices?model={model}", "kind": "openai"}
    return {"name": cfg.get("name") or pid, "kind": "cloud", "custom": True, "type": cfg.get("type", "openai"), "type_label": t["label"],
            "icon": None, "letter": _letter(cfg.get("name") or pid), "region": "自定义", "base_url": base,
            "about": f"自定义 Provider（{t['label']}）· {base}",
            "credentials": [{"env": env, "label": "API Key"}] if env else [], "optional": [],
            "console": cfg.get("console") or None, "docs": cfg.get("docs") or None,
            "adapter": t["adapter"], "key_env": env, "compat": compat, "config": cfg,
            "discover": {"kind": "openai_models", "public": not needs_key, **({"match": cfg["model_filter"].lower()} if cfg.get("model_filter") else {})},
            "model_defaults": {"caps": caps, "params": params, "voices": voices, "languages": ["多语言"], "license": "自定义", "family": cfg.get("name") or pid},
            # 同一个服务的 /audio/transcriptions：手动添加识别模型时用（vox models add <id>/<模型> --task stt）
            "stt": {"compat": {"response": "json"}, "model_defaults": {"languages": ["多语言"], "license": "自定义", "family": cfg.get("name") or pid}}}


def rebuild():
    """重新组装 MODELS：注册表 → 用户手动添加 → 在线列表缓存；同一个模型只保留最先出现的（注册表优先）。"""
    global REG
    REG = load_registry()
    PROVIDERS.clear()
    PROVIDERS.update(REG["providers"])
    for pid, cfg in _read(paths.CUSTOM_PROVIDERS, {}).items():   # 自定义 Provider 不能占用注册表里的 ID
        if pid not in PROVIDERS and isinstance(cfg, dict) and cfg.get("base_url"):
            PROVIDERS[pid] = custom_provider(pid, cfg)
    VOICE_SETS.clear()
    VOICE_SETS.update(REG.get("voice_sets", {}))
    out, seen = [], set()

    def key(m):
        return (m["provider"], m.get("repo") or m.get("remote") or m["id"]) if m["provider"] == "local" else (m["provider"], m["remote"])

    def add(m):
        if m and m["id"] not in seen and key(m) not in seen:
            seen.update((m["id"], key(m)))
            out.append(m)

    for e in REG["models"]:
        add(materialize({**e, "task": "tts"}, "registry"))
    for e in REG.get("stt_models", []):
        add(materialize({**e, "task": "stt"}, "registry"))
    templates = {m["id"]: m for m in out}
    for pid in PROVIDERS:   # 模板默认用同家同任务的第一个注册表模型：{pid}:*（合成）、{pid}:stt:*（识别）
        for task in TASKS:
            first = next((m for m in out if m["provider"] == pid and m["task"] == task), None)
            if first:
                templates.setdefault(tpl_key(pid, task), first)
    # 用户手动添加的排在在线列表前面：在线列表只给模型 ID，是合成还是识别靠猜；用户明确说过的以用户为准
    for e in _read(PREFS, {}).get("custom", []):
        e = {**e, "template": e.get("template") or tpl_key(e.get("provider"), e.get("task", "tts"))}
        add(materialize(e, "custom", templates))
    for f in sorted(DISCOVERED.glob("*.json")) if DISCOVERED.exists() else []:
        for e in _read(f, {}).get("items", []):
            e = {**e, "template": e.get("template") or (tpl_key(e.get("provider"), e.get("task", "tts")) if not e.get("caps") else None)}
            add(materialize(e, "discovered", templates))
    MODELS[:] = out
    _BY_ID.clear()
    for m in out:
        _BY_ID.setdefault(m["id"], m)
    for m in out:
        if m.get("alias"):
            _BY_ID.setdefault(m["alias"], m)


def tpl_key(pid: str, task: str = "tts") -> str:
    return f"{pid}:*" if task == "tts" else f"{pid}:{task}:*"


def find_model(mid: str) -> dict | None:
    """接受完整 ID（local/qwen3）、短名（qwen3）或 OpenAI 风格的裸名（gpt-4o-mini-tts）。"""
    if not mid:
        return None
    if mid in _BY_ID:
        return _BY_ID[mid]
    for m in MODELS:
        if mid == m["id"].split("/", 1)[-1]:
            return m
    return None


def short(m: dict) -> str:
    return m.get("alias") or m["id"]


def provider_template(pid: str, template: str | None = None, task: str = "tts") -> dict | None:
    """在线查到的新模型借用哪个已登记模型的配置。"""
    if template:
        return find_model(template)
    return next((m for m in MODELS if m["provider"] == pid and m["task"] == task and m["source"] == "registry"), None)


# ---------- WebUI / CLI 用的文案 ----------
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

rebuild()
