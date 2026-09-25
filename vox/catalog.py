"""模型目录：从注册表数据、在线列表和用户添加的条目，组装出 vox 认识的全部模型。

统一命名（CLI、HTTP、WebUI 共用）：
  模型 ID    提供方/模型，如 local/qwen3、openai/gpt-4o-mini-tts；本地模型也接受短名 qwen3
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
  voice_sets       可复用的静态音色表
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
BASE_CAPS = {"voices": True, "instructions": False, "design": False, "seed": False, "native_speed": True}
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


def materialize(entry: dict, source: str, templates: dict | None = None) -> dict | None:
    """把注册表 / 在线列表 / 用户添加的条目补全成完整的模型字典。Provider 未知或没有可用的适配器时返回 None。"""
    pid = entry.get("provider")
    p = PROVIDERS.get(pid)
    if not p:
        return None
    tpl = (templates or {}).get(entry.get("template")) if entry.get("template") else None
    if tpl:
        base = {k: v for k, v in copy.deepcopy(tpl).items() if k not in TEMPLATE_DROP}
        caps = dict(tpl["caps"])
    else:
        base = copy.deepcopy(p.get("model_defaults", {}))
        caps = {**BASE_CAPS, **base.pop("caps", {})}
    m = {**base, **{k: v for k, v in copy.deepcopy(entry).items() if k != "template"}}
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
    m["voices"] = voice_list(m.get("voices"))
    if m["voices"] != "engine":
        m.setdefault("default_voice", (m["voices"][0]["voice"] if m["voices"] else None))
    m["source"] = source
    m["inferred"] = entry.get("inferred", bool(entry.get("template")) and not entry.get("caps"))
    return m


def rebuild():
    """重新组装 MODELS：注册表 → 在线列表缓存 → 用户手动添加；同一个模型只保留最先出现的（注册表优先）。"""
    global REG
    REG = load_registry()
    PROVIDERS.clear()
    PROVIDERS.update(REG["providers"])
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
        add(materialize(e, "registry"))
    templates = {m["id"]: m for m in out}
    for pid in PROVIDERS:   # 模板默认用同家第一个注册表模型
        first = next((m for m in out if m["provider"] == pid), None)
        if first:
            templates.setdefault(f"{pid}:*", first)
    for f in sorted(DISCOVERED.glob("*.json")) if DISCOVERED.exists() else []:
        for e in _read(f, {}).get("items", []):
            e = {**e, "template": e.get("template") or (f"{e.get('provider')}:*" if not e.get("caps") else None)}
            add(materialize(e, "discovered", templates))
    for e in _read(PREFS, {}).get("custom", []):
        e = {**e, "template": e.get("template") or f"{e.get('provider')}:*"}
        add(materialize(e, "custom", templates))
    MODELS[:] = out
    _BY_ID.clear()
    for m in out:
        _BY_ID.setdefault(m["id"], m)
    for m in out:
        if m.get("alias"):
            _BY_ID.setdefault(m["alias"], m)


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


def provider_template(pid: str, template: str | None = None) -> dict | None:
    """在线查到的新模型借用哪个已登记模型的配置。"""
    if template:
        return find_model(template)
    return next((m for m in MODELS if m["provider"] == pid and m["source"] == "registry"), None)


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
