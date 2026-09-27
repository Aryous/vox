"""vox：本地 TTS 命令行。与 WebUI / HTTP API 共用同一套模型 ID、音色引用和参数名；所有命令都支持 --json。

  vox models                      我的模型（能直接用的）；--all 含未下载、未连接的；-p gemini 只看一家
  vox models fetch openrouter     在线查询这家现在提供的模型（local = HuggingFace）
  vox models add qwen3            加进我的模型：本地 = 下载，云端 = 加入清单；未登记的写 provider/模型名
  vox models rm <模型 ID>          移出我的模型（本地要加 --delete-files，会删除模型文件）
  vox models update               拉取新版模型注册表（只是数据，不含代码）
  vox voices -m qwen3             音色库
  vox sample qwen3:serena --play  试听音色样本
  vox say "你好" -m qwen3 -v serena -i "轻快友好" -o hi.mp3 --play
  vox history --star              历史（与 WebUI 共享）
  vox batch script.json -o vo/    多角色脚本批量合成
  vox keys set MINIMAX_API_KEY    配置云端 Provider 的 Key（输入不回显）
  vox providers add my-kokoro --base-url http://127.0.0.1:8880/v1 --no-key
                                  自定义 Provider（OpenAI 兼容：自建服务、代理、新厂商）
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

from . import paths


def _find_server():
    """VOX_URL 明确指定的服务直接用；否则看当前数据目录的 server.json（服务启动时写、退出时删），最后才试默认端口。"""
    if os.environ.get("VOX_URL"):
        return os.environ["VOX_URL"].rstrip("/"), True
    try:
        info = json.loads(paths.SERVER_FILE.read_text())
        os.kill(info["pid"], 0)
        return info["url"].rstrip("/"), False
    except ProcessLookupError:
        paths.SERVER_FILE.unlink(missing_ok=True)   # 服务没正常退出留下的
    except (OSError, ValueError, KeyError):
        pass
    return "http://127.0.0.1:8765", False


SERVER, _EXPLICIT = _find_server()
_SAME_HOME = None   # 第一次调用服务时核对：服务用的数据目录必须和本进程一致，否则改的是别人的数据
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
    global _SAME_HOME
    if os.environ.get("VOX_NO_SERVER"):
        return None
    if _SAME_HOME is None:
        _SAME_HOME = _EXPLICIT or _check_home()
    if not _SAME_HOME:
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


def _check_home():
    try:
        with urllib.request.urlopen(SERVER + "/api/status", timeout=3) as r:
            home = json.loads(r.read()).get("home")
    except (urllib.error.URLError, ConnectionError, TimeoutError, ValueError):
        return False   # 没有服务在跑
    if home and Path(home).expanduser().resolve() == paths.HOME.resolve():
        return True
    _log(f"注意：{SERVER} 上的 vox 服务用的是另一个数据目录（{home}），本次不经过它，直接在本进程里处理（{paths.HOME}）。"
         "确实要用那个服务，请设置 VOX_URL。")
    return False


def _hub():
    from . import hub

    return hub


def _fmt_size(n):
    return f"{n / 1e9:.2f} GB" if n >= 1e8 else f"{n / 1e6:.0f} MB"


STATUS_LABEL = {"loaded": "已加载", "ready": "可用", "not_downloaded": "未下载", "downloading": "下载中", "needs_key": "未连接"}


# ---------- 模型 ----------
def cmd_models(a):
    hub = _hub()
    act, tgt = a.action or "list", a.target
    if act in ("fetch", "add", "rm") and not tgt:
        raise SystemExit(f"vox models {act} 需要参数，例如 " + {"fetch": "vox models fetch openrouter", "add": "vox models add qwen3", "rm": "vox models rm openai/gpt-4o-mini-tts"}[act])
    if act == "fetch":
        r = _server("/api/providers/discover", {"provider": tgt}) or _call(hub.discover, tgt)
        return _out(a, r, lambda: [print(f"✓ 查到 {r['found']} 个模型"), _print_models(r["models"])])
    if act == "add":
        m = hub.catalog.find_model(tgt)
        if m and m["provider"] == "local" and _server("/api/status") is None:   # 没有服务在跑：本进程前台下载
            return _out(a, _call(hub.pull, tgt, False), lambda: None)
        r = _server("/api/models/add", {"model": tgt, "name": a.name}) or _call(hub.add_model, tgt, name=a.name)
        if r.get("state"):   # 本地模型：开始下载
            return _out(a, r, lambda: print(f"↓ 开始下载 {r['model']}；进度：vox status，或在 WebUI 模型页查看"))
        return _out(a, r, lambda: print(f"✓ 已加进我的模型：{r['model']}"))
    if act == "rm":
        r = _server("/api/models/remove", {"model": tgt, "delete_files": a.delete_files}) or _call(hub.remove_model, tgt, a.delete_files)
        return _out(a, r, lambda: print(f"✓ 已移出我的模型：{r['model']}" + (f"（已删除 {r['deleted']}）" if r.get("deleted") else "")))
    if act == "update":
        r = _server("/api/registry/update", {"url": tgt}) or _call(hub.registry_update, tgt)
        return _out(a, r, lambda: print(f"{'✓ 已更新' if r['changed'] else '已是最新'}：注册表 {r['updated']}（{r['providers']} 家 Provider，{r['models']} 个登记模型）"))
    qs = "&".join(x for x in (f"provider={a.provider}" if a.provider else "", "" if a.all else "mine=1") if x)
    ms = _server("/api/models?" + qs) or hub.models(a.provider, None if a.all else True)
    _out(a, ms, lambda: _print_models(ms) if ms else print("我的模型是空的。vox models --all 查看可以下载 / 添加的模型"))


def _call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except ValueError as e:
        raise SystemExit(f"✗ {e}")


def _print_models(ms):
    for m in ms:
        caps = "、".join(k for k, v in {"音色": m["caps"]["voices"], "指令": m["caps"]["instructions"], "设计": m["caps"]["design"], "种子": m["caps"]["seed"]}.items() if v)
        mark = "●" if m["mine"] else "○"
        print(f"{mark} {m['id']:<44} {STATUS_LABEL.get(m['status'], m['status']):<5} {m['name']}  [{caps}]")


def cmd_pull(a):
    r = _call(_hub().pull, a.model, False, a.source)   # 前台下载，进度打到 stderr
    _out(a, r, lambda: None)


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
    req = {**_request(a), "input": text, **({"cache": False} if a.no_cache else {})}
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
    keys = ("model", "voice", "instructions", "speed", "lang", "seed", *GEN)
    jobs = []
    for name, ln in _items(script):
        cfg = {**defaults, **roles.get(ln.get("who", ""), {}), **{k: ln[k] for k in keys if k in ln}}
        if a.model:
            cfg["model"] = a.model
        if a.seed is not None:
            cfg.setdefault("seed", a.seed)
        req = hub.normalize({**{k: cfg[k] for k in keys if k in cfg}, "input": ln.get("v", ln["s"])})
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
                if not p["connected"]:
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


def cmd_providers(a):
    hub = _hub()
    act = a.action or "list"
    if act == "list":
        ps = _server("/api/providers") or hub.provider_list()

        def human():
            for p in ps:
                where = p.get("base_url") or ("本机" if p["kind"] == "local" else p.get("region", ""))
                state = "本机" if p["kind"] == "local" else "已连接" if p["connected"] else "未连接"
                print(f"{_pad(p['id'], 14)} {_pad(p['name'], 16)} {_pad(state, 7)} 我的模型 {_pad(f"{p['mine']}/{p['count']}", 6)} {'自定义 · ' if p.get('custom') else ''}{where}")
        return _out(a, ps, human)
    if not a.id:
        raise SystemExit(f"vox providers {act} 需要 Provider ID，例如 vox providers {act} my-kokoro")
    if act == "rm":
        r = _server("/api/providers/remove", {"id": a.id}) or _call(hub.provider_remove, a.id)
        return _out(a, r, lambda: print(f"✓ 已删除自定义 Provider {a.id}（连同它在我的模型里的条目和保存的 Key）"))
    if act == "test" and not a.base_url:
        r = _server("/api/providers/test", {"id": a.id}) or _call(hub.provider_test, None, a.id)
        return _out(a, r, lambda: _print_test(r))
    # add / edit：edit 在原配置上改；没给的选项保持不变
    cur = {} if act == "add" else ((hub.catalog.PROVIDERS.get(a.id) or {}).get("config") or {})
    if act == "edit" and not cur:
        raise SystemExit(f"没有叫 {a.id} 的自定义 Provider")
    cfg = {**cur, **{k: v for k, v in {"name": a.name, "base_url": a.base_url, "instructions": a.instructions, "voices": a.voices,
                                        "model_filter": a.model_filter}.items() if v is not None}}
    for flag, key in (("no_key", "auth"), ("no_native_speed", "native_speed"), ("no_fetch_voices", "fetch_voices")):
        if getattr(a, flag):
            cfg[key] = False
    cfg.setdefault("auth", True)
    key = None
    if cfg.get("auth") and act == "add":
        if sys.stdin.isatty():
            import getpass

            key = getpass.getpass("API Key（输入不回显；回车跳过，之后用 vox keys set 补）：") or None
        else:
            key = sys.stdin.read().strip() or None
    if act == "test":
        r = _server("/api/providers/test", {"config": cfg, "key": key}) or _call(hub.provider_test, cfg, None, key)
        return _out(a, r, lambda: _print_test(r))
    r = _server("/api/providers/add", {"id": a.id, "config": cfg, "key": key, "overwrite": act == "edit"}) or _call(hub.provider_save, a.id, cfg, key, act == "edit")

    def human():
        print(f"✓ 已{'保存' if act == 'edit' else '添加'}自定义 Provider {r['provider']}")
        if r.get("key_env") and not r["connected"]:
            print(f"  还没有 Key：vox keys set {r['key_env']}")
        if r.get("found") is not None:
            print(f"  查到 {r['found']} 个模型；vox models -p {r['provider']} --all 查看，vox models add {r['provider']}/<模型> 加进我的模型")
        if r.get("error"):
            print(f"  查询模型列表失败：{r['error']}（可以手动添加：vox models add {r['provider']}/<模型>）")
    _out(a, r, human)


def _pad(s, w):
    """按显示宽度补空格（中文占两格），让中英混排的列对齐。"""
    import unicodedata

    n = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))
    return str(s) + " " * max(0, w - n)


def _print_test(r):
    if r["ok"]:
        print(f"✓ 连得上 {r['base_url']}：{len(r['models'])} 个模型" + (f"，{r['voices']} 个音色" if r.get("voices") is not None else "，没有音色列表接口（可以手动填音色）"))
        for m in r["models"][:20]:
            print(f"  {m}")
    else:
        print(f"✗ {r['error']}")


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

    s = J(sub.add_parser("models", help="我的模型：list / fetch <provider> / add <模型> / rm <模型> / update"))
    s.add_argument("action", nargs="?", choices=["list", "fetch", "add", "rm", "update"])
    s.add_argument("target", nargs="?", help="Provider（fetch）、模型 ID（add / rm）或注册表地址（update）")
    s.add_argument("-p", "--provider", help="只看某一家")
    s.add_argument("--all", action="store_true", help="也列出还不能用的（未下载、未连接、未添加）")
    s.add_argument("--name", help="手动添加时的显示名")
    s.add_argument("--delete-files", action="store_true", help="rm 本地模型时确认删除已下载的文件")
    s.set_defaults(fn=cmd_models)
    s = J(sub.add_parser("pull", help="下载模型（ModelScope，按 HuggingFace 哈希校验）"))
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
    s.add_argument("-m", "--model", dest="model", help="模型 ID，默认 local/qwen3（环境变量 VOX_MODEL 可改）")
    s.add_argument("-v", "--voice", help="音色，如 serena；也可写引用 qwen3:serena / my:<id>")
    s.add_argument("-i", "--instructions", dest="instructions", help="情绪 / 语气；声音设计模型里是声音描述")
    s.add_argument("-s", "--speed", type=float, help="语速 0.25–4")
    s.add_argument("--seed", type=int, help="随机种子（Qwen3 可复现）；不填则随机并记录")
    s.add_argument("--no-cache", action="store_true", help="不用缓存，重新合成（不支持种子的云端模型用它再来一条）")
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

    s = J(sub.add_parser("providers", help="Provider：list / add / edit / rm / test（自定义 Provider 用 OpenAI 兼容接口接入）"))
    s.add_argument("action", nargs="?", choices=["list", "add", "edit", "rm", "test"])
    s.add_argument("id", nargs="?", help="Provider ID，如 my-kokoro")
    s.add_argument("--base-url", help="如 http://127.0.0.1:8880/v1（POST {base}/audio/speech）")
    s.add_argument("--name", help="显示名")
    s.add_argument("--no-key", action="store_true", help="这个服务不需要 Key（本机自建常见）")
    s.add_argument("--instructions", choices=["instructions", "instruction", "prefix", "none"], help="情绪指令怎么传，默认 instructions")
    s.add_argument("--no-native-speed", action="store_true", help="服务不支持 speed，改由 ffmpeg 变速")
    s.add_argument("--voices", help="手动指定音色，逗号分隔")
    s.add_argument("--no-fetch-voices", action="store_true", help="不去 {base}/audio/voices 拉音色列表")
    s.add_argument("--model-filter", help="在线模型列表只保留名字含这个词的")
    s.set_defaults(fn=cmd_providers)

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
