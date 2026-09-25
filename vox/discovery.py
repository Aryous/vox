"""在线发现：向各 Provider（和 HuggingFace）查询现在有哪些 TTS 模型。

每家怎么查写在注册表的 providers.<id>.discover 里（kind + 参数），这里只实现几种查询方式：
  huggingface     本地模型：HuggingFace 模型搜索（公开接口），只保留 vox 引擎能直接运行的仓库
  openrouter      OpenRouter /api/v1/models?output_modalities=speech（公开接口，带音色和价格）
  openai_models   OpenAI 风格的 GET {base}/models；match / exclude 按模型名过滤（列表里没有能力字段时只能这样认）
  elevenlabs      GET /v1/models，can_do_text_to_speech 标出 TTS 模型
  gemini          GET /v1beta/models（分页），按名字里的 tts 识别
结果缓存到 <缓存目录>/discovered/<provider>.json（见 paths.py），catalog.rebuild() 会把它们并进模型目录。
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from . import catalog, credentials
from .providers.base import ProviderError, http

HF = "https://huggingface.co"
MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def _plain(text: str, n=280) -> str:
    """在线列表里的描述常带 Markdown 链接，界面只要纯文本。"""
    return MD_LINK.sub(r"\1", (text or "").strip())[:n]


def supported(pid: str) -> dict | None:
    return (catalog.PROVIDERS.get(pid) or {}).get("discover")


def cached(pid: str) -> dict | None:
    return catalog._read(catalog.DISCOVERED / f"{pid}.json", None)


def needs_key(pid: str) -> bool:
    d = supported(pid) or {}
    return not d.get("public")


def run(pid: str) -> dict:
    """查询并缓存。返回 {"fetched", "items"}；失败抛 ProviderError。"""
    p = catalog.PROVIDERS.get(pid)
    d = supported(pid)
    if not p:
        raise ProviderError(f"未知的 Provider「{pid}」")
    if not d:
        raise ProviderError(f"{p['name']} 没有公开的模型列表接口，只能手动填模型 ID")
    if needs_key(pid) and not all(credentials.get(c["env"]) for c in p.get("credentials", [])):
        raise ProviderError(f"先连接 {p['name']}（填 Key），再获取模型列表")
    items = KINDS[d["kind"]](pid, p, d)
    for it in items:
        it.setdefault("provider", pid)
    res = {"fetched": time.time(), "kind": d["kind"], "items": items}
    catalog.DISCOVERED.mkdir(parents=True, exist_ok=True)
    (catalog.DISCOVERED / f"{pid}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    catalog.rebuild()
    return res


def _key(p: dict) -> str | None:
    return credentials.get(p["credentials"][0]["env"]) if p.get("credentials") else None


# ---------- 本地：HuggingFace ----------
def _hf_entry(repo: str, rule: dict, downloads: int) -> dict:
    tail = repo.split("/", 1)[-1]
    slug = re.sub(r"-12hz", "", tail.lower())
    size = re.search(r"(\d+(?:\.\d+)?)B", tail)
    quant = re.search(r"(\d+bit|bf16|fp16)$", tail, re.I)
    kind = rule["match"]
    return {"provider": "local", "id": f"local/{slug}", "alias": slug, "repo": repo, "template": rule["template"],
            "name": f"Qwen3-TTS {kind} {size[1] + 'B' if size else ''} · {quant[1] if quant else ''}".replace("  ", " ").strip(" ·"),
            "params_b": float(size[1]) if size else None, "quant": f"MLX {quant[1]}" if quant else "MLX",
            "size_gb": None, "downloads": downloads, "inferred": False, "homepage": f"{HF}/{repo}",
            "about": f"来自 HuggingFace（{repo.split('/')[0]}），下载 {downloads:,} 次。用 vox 的 {rule['template'].split('/')[-1]} 引擎运行，能力同该模型。"}


def _hf_size(repo: str) -> float | None:
    try:
        _, _, body = http("GET", f"{HF}/api/models/{repo}/tree/main?recursive=true", timeout=20)
        return round(sum(x.get("size", 0) for x in json.loads(body) if x.get("type") == "file") / 1e9, 2)
    except (ProviderError, ValueError):
        return None


def huggingface(pid, p, d):
    q = f"author={quote(d['author'])}&search={quote(d['search'])}&limit=200"
    _, _, body = http("GET", f"{HF}/api/models?{q}", timeout=30)
    out = []
    for r in json.loads(body):
        rule = next((x for x in d["rules"] if x["match"] in r["id"]), None)
        if rule:
            out.append(_hf_entry(r["id"], rule, r.get("downloads", 0)))
    with ThreadPoolExecutor(8) as ex:   # 大小要逐个查文件树，并发查，失败的留空
        for e, size in zip(out, ex.map(_hf_size, [e["repo"] for e in out])):
            e["size_gb"] = size
    return sorted(out, key=lambda e: (e["template"], e["params_b"] or 0, -e["downloads"]))


# ---------- 云端 ----------
def openrouter(pid, p, d):
    key = _key(p)
    _, _, body = http("GET", "https://openrouter.ai/api/v1/models?output_modalities=speech", {"Authorization": f"Bearer {key}"} if key else {}, timeout=30)
    out = []
    for m in json.loads(body).get("data", []):
        pr = m.get("pricing") or {}
        pin, pout = float(pr.get("prompt") or 0), float(pr.get("completion") or 0)
        if pin == 0 and pout == 0:
            price = {"text": "免费", "unit": "token"}
        elif pout == 0:   # 纯按输入字符计费
            price = {"amount": round(pin * 1e6, 4), "currency": "USD", "per": 1_000_000, "unit": "char"}
        else:
            price = {"text": f"输入 ${pin * 1e6:g} + 输出 ${pout * 1e6:g} / 百万 token", "unit": "token"}
        vs = m.get("supported_voices") or []
        out.append({"remote": m["id"], "name": m.get("name") or m["id"], "about": _plain(m.get("description")),
                    "voices": vs, "price": price, "caps": {"voices": bool(vs)}, "homepage": f"https://openrouter.ai/{m['id']}"})
    return out


def openai_models(pid, p, d):
    base = credentials.get(p.get("compat", {}).get("base_env", "")) if p.get("compat", {}).get("base_env") else None
    base = base or p["compat"]["base"]
    key = _key(p)
    _, _, raw = http("GET", f"{base}/models{d.get('query', '')}", {"Authorization": f"Bearer {key}"} if key else {}, timeout=30)
    out = []
    for m in json.loads(raw).get("data", []):
        mid = m.get("id", "")
        low = mid.lower()
        if (d.get("match") and d["match"] not in low) or any(x in low for x in d.get("exclude", ())):
            continue
        out.append({"remote": mid, "name": mid})
    return sorted(out, key=lambda r: r["remote"])


def elevenlabs(pid, p, d):
    _, _, body = http("GET", "https://api.elevenlabs.io/v1/models", {"xi-api-key": _key(p)}, timeout=30)
    return [{"remote": m["model_id"], "name": m.get("name") or m["model_id"], "about": _plain(m.get("description"))}
            for m in json.loads(body) if m.get("can_do_text_to_speech")]


def gemini(pid, p, d):
    out, token = [], ""
    for _ in range(5):
        _, _, body = http("GET", "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000" + (f"&pageToken={token}" if token else ""),
                          {"x-goog-api-key": _key(p)}, timeout=30)
        j = json.loads(body)
        for m in j.get("models", []):
            mid = m.get("name", "").removeprefix("models/")
            if "tts" in mid.lower():
                out.append({"remote": mid, "name": m.get("displayName") or mid, "about": _plain(m.get("description"))})
        token = j.get("nextPageToken")
        if not token:
            break
    return out


KINDS = {"huggingface": huggingface, "openrouter": openrouter, "openai_models": openai_models, "elevenlabs": elevenlabs, "gemini": gemini}
