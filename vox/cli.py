"""vox：本地 TTS 命令行。与 WebUI / HTTP API 共用同一套模型 ID、音色引用和参数名；所有命令都支持 --json。

  vox models                      模型列表与状态（-p gemini 只看一家）
  vox models fetch gemini         向 Provider 获取它现在提供的 TTS 模型
  vox models add gemini/<模型名>   把模型加进清单；off / on / rm 停用、启用、删除
  vox pull qwen3                  下载模型
  vox voices -m qwen3             音色库
  vox sample qwen3:serena --play  试听音色样本
  vox say "你好" -m qwen3 -v serena -i "轻快友好" -o hi.mp3 --play
  vox history --star              历史（与 WebUI 共享）
  vox batch script.json -o vo/    多角色脚本批量合成
  vox keys set MINIMAX_API_KEY    配置云端 Provider 的 Key（输入不回显）
  vox serve --open                本地服务：WebUI + OpenAI 兼容 API

vox 服务在运行时（默认 http://127.0.0.1:8765），say / sample / load / unload 会交给服务执行，直接用已加载的模型。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SERVER = os.environ.get("VOX_URL", "http://127.0.0.1:8765").rstrip("/")
GEN = ("temperature", "top_p", "top_k", "repetition_penalty")


def _log(*a):
    print(*a, file=sys.stderr, flush=True)


def _out(a, data, human):
    """--json 时输出 JSON，否则调用 human() 打印给人看的格式。"""
    if getattr(a, "json", False):
        print(json.dumps(data, ensure_ascii=False, indent=1))
    else:
        human()


def _server(path, body=None, timeout=600):
    """调用正在运行的 vox 服务；没在运行返回 None。"""
    if os.environ.get("VOX_NO_SERVER"):
        return None
    try:
        req = urllib.request.Request(SERVER + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        msg = json.loads(e.read() or b"{}").get("error", str(e))
        raise SystemExit(f"✗ {msg}")
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return None


def _hub():
    from . import hub

    return hub


def _fmt_size(n):
    return f"{n / 1e9:.2f} GB" if n >= 1e8 else f"{n / 1e6:.0f} MB"


STATUS_LABEL = {"loaded": "已加载", "ready": "已下载", "not_downloaded": "未下载", "downloading": "下载中", "planned": "即将支持", "unavailable": "不可用", "needs_key": "需 Key"}


# ---------- 模型 ----------
def cmd_models(a):
    hub = _hub()
    act, tgt = a.action or "list", a.target
    if act != "list" and not tgt:
        raise SystemExit(f"vox models {act} 需要参数，例如 " + {"fetch": "vox models fetch gemini", "add": "vox models add openai/tts-1"}.get(act, f"vox models {act} openai/gpt-4o-mini-tts"))
    if act == "fetch":
        rs = _server("/api/providers/discover", {"provider": tgt}) or hub.discover(tgt)
        return _out(a, rs, lambda: [print(f"{'✓ 已在清单' if r['added'] else '  可添加  '}  {r['id']:<40} {r.get('name') or ''}") for r in rs] or print("没有找到 TTS 模型"))
    if act == "add":
        prov, _, remote = tgt.partition("/")
        r = _server("/api/models/add", {"provider": prov, "remote": remote, "name": a.name}) or hub.add_model(prov, remote, a.name)
        return _out(a, r, lambda: print(f"✓ 已添加 {r['model']}"))
    if act in ("on", "off"):
        r = _server("/api/models/enable", {"model": tgt, "enabled": act == "on"}) or hub.set_enabled(tgt, act == "on")
        return _out(a, r, lambda: print(f"✓ {r['model']} 已{'启用' if r['enabled'] else '停用'}"))
    if act == "rm":
        r = _server("/api/models/remove", {"model": tgt}) or hub.remove_model(tgt)
        return _out(a, r, lambda: print(f"✓ 已从清单删除 {r['model']}"))
    ms = _server("/api/models" + (f"?provider={a.provider}" if a.provider else "")) or hub.models(a.provider)

    def human():
        for m in ms:
            caps = "、".join(k for k, v in {"预置音色": m["caps"]["voices"], "情绪指令": m["caps"]["instructions"], "声音设计": m["caps"]["design"], "可复现": m["caps"]["seed"]}.items() if v)
            print(f"{m['id']:<34} {STATUS_LABEL.get(m['status'], m['status']):<5} {'' if m['enabled'] else '已停用 '}{m['name']}  [{caps}]")
    _out(a, ms, human)


def cmd_pull(a):
    hub = _hub()
    m = hub.model_or_raise(a.model)
    if m["provider"] != "local" or m["engine"] == "kokoro":
        raise SystemExit("这个模型不需要手动下载" if m["provider"] == "local" else "云端模型无需下载")
    from . import fetch

    fetch.fetch(m["repo"], a.source)
    _out(a, hub.pull_status(m["id"]), lambda: None)


def cmd_load(a, unload=False):
    r = _server("/api/models/" + ("unload" if unload else "load"), {"model": a.model})
    if r is None:
        raise SystemExit("load / unload 作用于正在运行的 vox 服务：先运行 vox serve")
    _out(a, r, lambda: print(f"✓ {r['model']} {STATUS_LABEL.get(r['status'], r['status'])}" + (f"（{r['seconds']}s）" if r.get("seconds") else "")))


# ---------- 音色 ----------
def cmd_voices(a):
    qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in {"model": a.model, "lang": a.lang, "gender": a.gender, "q": a.query}.items() if v)
    vs = _server("/api/voices?" + qs) or _hub().voices(model=a.model, lang=a.lang, gender=a.gender, q=a.query)
    _out(a, vs, lambda: [print(f"{v['ref']:<22} {v['name']:<10} {v['gender'] or '-'} {v['lang'] or '-':<4} {v['description']}") for v in vs])


def cmd_sample(a):
    r = _server("/api/voices/sample", {"ref": a.ref})
    if r:
        r["file"] = str(_hub().SAMPLES / Path(r["url"]).name)
    else:
        r = _hub().sample(a.ref)
    _out(a, r, lambda: print(f"✓ {r['ref']}  {r['dur']}s  {r['file']}"))
    if a.play:
        subprocess.run(["afplay", r["file"]])


# ---------- 合成 ----------
def _request(a):
    req = {"model": a.model, "voice": a.voice, "instructions": a.instructions, "speed": a.speed, "seed": a.seed, "lang": a.lang,
           **{k: getattr(a, k) for k in GEN}}
    return {k: v for k, v in req.items() if v is not None}


def cmd_say(a):
    text = sys.stdin.read().strip() if a.text == "-" else a.text
    req = {**_request(a), "input": text}
    t = time.time()
    rec = None if a.local else _server("/api/speech", {**req, "source": "cli"})
    hub = _hub()
    rec = rec or hub.speak(req, source="cli")
    src = hub.clip_path(rec["id"])
    out = Path(a.output) if a.output else None
    if out:
        from . import audio

        shutil.copy2(audio.convert(src, out.suffix.lstrip(".").lower() or "wav"), out)
    rec = {**{k: v for k, v in rec.items() if k not in ("file", "url")}, "file": str(out or src)}
    _out(a, rec, lambda: _log(f"✓ {rec['file']}  {rec['dur']:.2f}s 音频，用时 {time.time() - t:.1f}s" + (f"，种子 {rec['request']['seed']}" if "seed" in rec["request"] else "")))
    if not a.json:
        print(rec["file"])
    if a.play:
        subprocess.run(["afplay", rec["file"]])


def cmd_history(a):
    h = _hub().history(a.limit, True if a.star else None)
    _out(a, h, lambda: [print(f"{x['id']}  {'★' if x.get('star') else ' '} {x['request']['model']:<18} {x['request'].get('voice') or '-':<10} {x['dur']:5.1f}s  {x['request']['input'][:30]}") for x in h])


def cmd_status(a):
    s = _server("/api/status")
    running = s is not None
    s = s or _hub().status()
    _out(a, {**s, "server": SERVER if running else None},
         lambda: print(f"服务：{SERVER if running else '未运行（vox serve 启动）'}\n已加载：{', '.join(s['loaded']) or '无'}\n内存：{_fmt_size(s['memory_bytes'])}\n读音校对：{'可用' if s['asr'] else '不可用（需要 coli）'}\n数据目录：{s['home']}"))


# ---------- 批量 ----------
def _items(script: dict):
    if "scenes" in script:
        for si, sc in enumerate(script["scenes"]):
            for li, ln in enumerate(sc["lines"]):
                yield f"s{si:02d}_{li:02d}", ln
    else:
        for i, ln in enumerate(script["lines"]):
            yield ln.get("id", f"{i:03d}"), ln


def cmd_batch(a):
    hub = _hub()
    from . import audio

    path = Path(a.script)
    script = json.loads(path.read_text())
    outdir = Path(a.output or path.parent / "vo")
    outdir.mkdir(parents=True, exist_ok=True)
    mpath = outdir / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {}
    roles, defaults = script.get("voices", {}), script.get("defaults", {})
    only = set(a.only.split(",")) if a.only else None
    keys = ("model", "engine", "voice", "instructions", "instruct", "speed", "lang", "seed", *GEN)
    jobs = []
    for name, ln in _items(script):
        cfg = {**defaults, **roles.get(ln.get("who", ""), {}), **{k: ln[k] for k in keys if k in ln}}
        if "engine" in cfg:  # 兼容旧脚本
            cfg.setdefault("model", cfg.pop("engine"))
        if a.model:
            cfg["model"] = a.model
        if a.seed is not None:
            cfg.setdefault("seed", a.seed)
        req = hub.normalize({**{k: cfg[k] for k in keys if k in cfg and k != "engine"}, "input": ln.get("v", ln["s"])})
        key = hashlib.sha1(json.dumps(req, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        fresh = manifest.get(name, {}).get("key") == key and (outdir / f"{name}.{a.format}").exists()
        if (only and name not in only) or (fresh and not a.force):
            continue
        jobs.append((name, req, key))
    _log(f"{sum(1 for _ in _items(script))} 句，本次合成 {len(jobs)} 句 → {outdir}")
    t0 = time.time()
    for n, (name, req, key) in enumerate(jobs, 1):
        t = time.time()
        rec = hub.speak(req, source="batch", record=False)
        shutil.copy2(audio.convert(Path(rec["file"]), a.format), outdir / f"{name}.{a.format}")
        manifest[name] = {"key": key, "dur": rec["dur"], "request": rec["request"]}
        mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
        _log(f"[{n}/{len(jobs)}] {name} {rec['dur']:5.2f}s ({time.time() - t:4.1f}s)  {req['input'][:28]}")
    if "scenes" in script:
        durs = [[manifest.get(f"s{si:02d}_{li:02d}", {}).get("dur") for li in range(len(sc["lines"]))] for si, sc in enumerate(script["scenes"])]
        (outdir / "timing.js").write_text("window.VO=" + json.dumps({"durs": durs, "format": a.format}) + ";\n")
    else:
        durs = {name: manifest.get(name, {}).get("dur") for name, _ in _items(script)}
    (outdir / "timing.json").write_text(json.dumps(durs, ensure_ascii=False))
    _out(a, {"outdir": str(outdir), "synthesized": len(jobs), "seconds": round(time.time() - t0)}, lambda: _log(f"✓ 完成，用时 {time.time() - t0:.0f}s"))


def cmd_keys(a):
    hub = _hub()
    if a.action == "list":
        ps = hub.provider_list()

        ps = [p for p in ps if p["kind"] == "cloud"]

        def human():
            for p in ps:
                for c in p["credentials"] + p["optional"]:
                    st = f"已配置（{'环境变量' if c['source'] == 'env' else '配置文件'}{'，…' + c['last4'] if c['last4'] else ''}）" if c["configured"] else ("未配置" if c in p["credentials"] else "—")
                    print(f"{p['name']:<12} {c['env']:<24} {st}")
                if not p["ready"]:
                    print(f"{'':<12} 申请：{p['console']}")
        return _out(a, ps, human)
    if not a.env:
        raise SystemExit("需要凭证名，例如 vox keys set OPENAI_API_KEY（vox keys list 查看全部）")
    if a.action == "set":
        value = a.value
        if value is None:
            if sys.stdin.isatty():
                import getpass

                value = getpass.getpass(f"{a.env}（输入不回显）：")
            else:
                value = sys.stdin.read().strip()
        r = hub.set_key(a.env, value)
        return _out(a, r, lambda: print(f"✓ 已保存到 {__import__('vox.credentials', fromlist=['PATH']).PATH}（权限 600）" + ("；注意：同名环境变量已设置，会优先生效" if r["source"] == "env" else "")))
    r = hub.delete_key(a.env)
    _out(a, r, lambda: print(f"✓ 已从配置文件删除 {a.env}" + ("（环境变量里仍有值）" if r["configured"] else "")))


def cmd_serve(a):
    from .server import serve

    serve(a.host, a.port, a.open)


# ---------- 参数 ----------
def main(argv=None):
    p = argparse.ArgumentParser(prog="vox", description="本地 TTS：统一接口调用多个模型。WebUI / HTTP API / CLI 共用同一套模型、音色与参数。",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="cmd", required=True, metavar="命令")

    def J(sp):
        sp.add_argument("--json", action="store_true", help="输出 JSON（给脚本和 Agent）")
        return sp

    s = J(sub.add_parser("models", aliases=["engines"], help="模型清单：list / fetch <provider> / add <provider>/<模型> / on / off / rm"))
    s.add_argument("action", nargs="?", choices=["list", "fetch", "add", "on", "off", "rm"])
    s.add_argument("target", nargs="?", help="Provider（fetch）或模型 ID")
    s.add_argument("-p", "--provider", help="只列出某一家")
    s.add_argument("--name", help="add 时的显示名")
    s.set_defaults(fn=cmd_models)
    s = J(sub.add_parser("pull", aliases=["fetch"], help="下载模型（ModelScope，按 HuggingFace 哈希校验）"))
    s.add_argument("model", help="模型 ID，如 qwen3、qwen3-design")
    s.add_argument("--source", default="modelscope", choices=["modelscope", "hf"])
    s.set_defaults(fn=cmd_pull)
    for name, un in (("load", False), ("unload", True)):
        s = J(sub.add_parser(name, help=("卸载" if un else "预加载") + "模型（作用于运行中的服务）"))
        s.add_argument("model")
        s.set_defaults(fn=lambda a, un=un: cmd_load(a, un))

    s = J(sub.add_parser("voices", help="音色库"))
    s.add_argument("-m", "--model")
    s.add_argument("--lang", help="如 中文、英语、北京话")
    s.add_argument("--gender", choices=["男", "女"])
    s.add_argument("-q", "--query", help="关键词")
    s.set_defaults(fn=cmd_voices)

    s = J(sub.add_parser("sample", help="试听音色样本（统一样本文本）"))
    s.add_argument("ref", help="音色引用，如 qwen3:serena、kokoro:zf_003、my:<id>")
    s.add_argument("--play", action="store_true")
    s.set_defaults(fn=cmd_sample)

    s = J(sub.add_parser("say", help="合成一句话"))
    s.add_argument("text", help="文本；- 表示从标准输入读取")
    s.add_argument("-m", "--model", "-e", "--engine", dest="model", help="模型 ID，默认 local/qwen3（环境变量 VOX_MODEL 可改）")
    s.add_argument("-v", "--voice", help="音色，如 serena；也可写引用 qwen3:serena / my:<id>")
    s.add_argument("-i", "--instructions", "--instruct", dest="instructions", help="情绪 / 语气；声音设计模型里是声音描述")
    s.add_argument("-s", "--speed", type=float, help="语速 0.25–4")
    s.add_argument("--seed", type=int, help="随机种子（Qwen3 可复现）；不填则随机并记录")
    s.add_argument("-l", "--lang", help="语言，如 chinese、english、auto")
    for k, t in (("temperature", float), ("top_p", float), ("top_k", int), ("repetition_penalty", float)):
        s.add_argument("--" + k.replace("_", "-"), dest=k, type=t)
    s.add_argument("-o", "--output", help="输出文件（.wav / .mp3 / .flac / .opus / .aac）；不填则留在 vox 数据目录")
    s.add_argument("--play", action="store_true", help="合成后播放")
    s.add_argument("--local", action="store_true", help="不走运行中的服务，在本进程合成")
    s.set_defaults(fn=cmd_say)

    s = J(sub.add_parser("history", help="合成历史（与 WebUI 共享）"))
    s.add_argument("-n", "--limit", type=int, default=20)
    s.add_argument("--star", action="store_true", help="只看收藏")
    s.set_defaults(fn=cmd_history)

    J(sub.add_parser("status", help="服务与模型状态")).set_defaults(fn=cmd_status)

    s = J(sub.add_parser("batch", help="按脚本 JSON 批量合成（只重做改动过的句子）"))
    s.add_argument("script")
    s.add_argument("-o", "--output", help="输出目录，默认脚本旁的 vo/")
    s.add_argument("-f", "--format", default="mp3", choices=["mp3", "wav", "flac"])
    s.add_argument("-m", "--model", help="强制所有台词用这个模型")
    s.add_argument("--only", help="只合成这些条目，逗号分隔")
    s.add_argument("--seed", type=int, help="没写种子的台词用这个种子")
    s.add_argument("--force", action="store_true", help="忽略缓存全部重做")
    s.set_defaults(fn=cmd_batch)

    s = J(sub.add_parser("keys", help="云端 Provider 的凭证：list / set / rm（环境变量优先，其次 ~/.config/vox/credentials.json）"))
    s.add_argument("action", choices=["list", "set", "rm"])
    s.add_argument("env", nargs="?", help="凭证名，如 OPENAI_API_KEY")
    s.add_argument("--value", help="直接给值（会留在 shell 历史里；推荐不填，交互输入或从管道读）")
    s.set_defaults(fn=cmd_keys)

    s = sub.add_parser("serve", help="启动本地服务：WebUI + OpenAI 兼容 API")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--host", default="127.0.0.1", help="默认只允许本机访问")
    s.add_argument("--open", action="store_true", help="启动后打开浏览器")
    s.set_defaults(fn=cmd_serve)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except ValueError as e:  # hub.VoxError
        raise SystemExit(f"✗ {e}")


if __name__ == "__main__":
    main()
