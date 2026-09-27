"""vox serve：本地服务，一个端口承载三样东西——
  /           WebUI
  /api/*      原生 API（WebUI 用的就是它，Agent 也可以用）
  /v1/*       OpenAI 兼容 API：POST /v1/audio/speech、GET /v1/models
  /llms.txt   给 Agent 看的接口说明
默认只监听 127.0.0.1。
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import audio, catalog, hub, paths

WEB = Path(__file__).parent / "web"


def llms_txt(base: str) -> str:
    ms = "\n".join(f"- {m['id']}{'（短名 ' + m['alias'] + '）' if m.get('alias') and m['alias'] != m['id'] else ''}：{m['name']}，参数 {', '.join(m['params'])}" for m in hub.models(mine=True))
    return f"""# vox

> 本地 TTS 服务：统一接口调用多个 TTS 模型。OpenAI 兼容，CLI / HTTP / WebUI 用同一套模型 ID、音色 ID 和参数名。

## 我的模型（能直接调用的）
{ms}
全部模型（含未下载、未连接）：GET /api/models；只看我的：?mine=1；只看某家：?provider=

## 合成（OpenAI 兼容）
POST {base}v1/audio/speech
{{"model": "local/qwen3", "input": "你好", "voice": "serena", "instructions": "轻快友好", "speed": 1.0, "response_format": "mp3"}}
扩展参数：seed（可复现）、lang、temperature、top_p、top_k、repetition_penalty；cache=false 跳过缓存重新合成（同样的请求默认直接返回上次的结果）。voice 也可写音色引用，如 "qwen3:serena" 或 "my:<id>"。
返回音频字节；响应头 X-Vox-Id、X-Vox-Seed、X-Vox-Duration。

## 原生 API（JSON）
GET  /api/models                 模型与状态（not_downloaded / downloading / ready / loaded / needs_key），mine 表示在「我的模型」里
POST /api/models/add {{"model"}} 或 {{"provider","remote"}}   加进我的模型（本地 = 开始下载）；GET /api/models/pull?model= 查下载进度
POST /api/models/remove {{"model","delete_files"?}}   移出我的模型（本地要 delete_files: true，会删除模型文件）
POST /api/providers/discover {{"provider"}}   在线查询这家现在提供的模型（本地 = HuggingFace）
POST /api/models/load | /api/models/unload {{"model"}}
GET  /api/voices?model=&lang=&gender=&q=   音色库
POST /api/voices/sample {{"ref": "qwen3:serena"}}   生成 / 取音色样本
POST /api/speech {{同 /v1/audio/speech}}   返回 JSON：id、request（含实际种子）、dur、url
GET  /api/history?limit=&star=   POST /api/history/update {{"id","star"|"delete"}}   POST /api/asr {{"id"}}
GET/POST /api/my-voices          自定义音色；POST /api/my-voices/delete {{"id"}}
GET  /api/status                 服务状态、已加载模型、内存
GET  /api/providers              Provider 与连接状态；POST /api/keys {{"env","value"}} 保存凭证（不会回显）
GET  /api/registry | POST /api/registry/update   模型注册表版本 / 拉取新版
POST /api/providers/add {{"id","config":{{"name","base_url","auth","instructions","native_speed","fetch_voices","voices","model_filter"}},"key"?,"overwrite"?}}
     自定义 Provider（OpenAI 兼容：自建服务、代理、新厂商）；POST /api/providers/test 同样的参数只试连不保存；POST /api/providers/remove {{"id"}}
GET  /v1/audio/voices?model=     音色列表（扩展，与 Kokoro-FastAPI 同写法）：另一台 vox 可以把这台当自定义 Provider 接入

## CLI 等价
vox models --json | vox models --all | vox models fetch openrouter | vox models add <模型 ID> | vox voices -m qwen3 --json | vox say "你好" -m qwen3 -v serena -i "轻快友好" --json
"""


class Handler(SimpleHTTPRequestHandler):
    server_version = "vox"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB), **kw)

    def log_message(self, fmt, *args):
        if self.path.startswith(("/api/", "/v1/")):
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")  # 方便本机其他页面 / 工具调用
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Expose-Headers", "X-Vox-Id, X-Vox-Seed, X-Vox-Duration")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    # ---- 响应工具 ----
    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, f: Path, ctype: str, extra: dict | None = None, cache=True):
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if cache:
            self.send_header("Cache-Control", "max-age=31536000, immutable")
        for k, v in (extra or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            raise hub.VoxError("请求体不是合法 JSON")

    def _run(self, fn, openai=False):
        try:
            res = fn()
            if res is not None:
                self._json(res)
        except (hub.VoxError, SystemExit, ValueError) as e:
            msg = str(e)
            self._json({"error": {"message": msg, "type": "invalid_request_error"}} if openai else {"error": msg}, 400)
        except Exception as e:
            traceback.print_exc()
            self._json({"error": {"message": str(e), "type": "server_error"}} if openai else {"error": f"{type(e).__name__}: {e}"}, 500)

    # ---- 路由 ----
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path
        if p == "/llms.txt":
            body = llms_txt(f"http://{self.headers.get('Host', '127.0.0.1')}/").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if p == "/v1/audio/voices":   # 扩展：音色列表（与 Kokoro-FastAPI 等服务同一写法），别的 vox 或工具可以把 vox 当 Provider 接入
            return self._run(lambda: {"voices": [{"id": v["voice"] if q.get("model") else v["ref"], "name": v["name"], "gender": v["gender"],
                                                  "lang": v["lang"], "description": v["description"]}
                                                 for v in hub.voices(model=q.get("model"), with_samples=False) if v["kind"] == "preset"]}, openai=True)
        if p == "/v1/models":
            return self._run(lambda: {"object": "list", "data": [
                {"id": m["id"], "object": "model", "created": 0, "owned_by": m["provider"], "status": m["status"]} for m in hub.models(mine=True)]}, openai=True)
        routes = {
            "/api/status": hub.status,
            "/api/models": lambda: hub.models(q.get("provider"), {"1": True, "0": False}.get(q.get("mine", ""))),
            "/api/registry": hub.registry_info,
            "/api/models/pull": lambda: hub.pull_status(q.get("model", "")),
            "/api/voices": lambda: hub.voices(model=q.get("model"), lang=q.get("lang"), gender=q.get("gender"), q=q.get("q")),
            "/api/history": lambda: hub.history(int(q["limit"]) if q.get("limit") else None, {"1": True, "0": False}.get(q.get("star", ""))),
            "/api/my-voices": hub.my_voices,
            "/api/settings": hub.settings,
            "/api/catalog": lambda: {"instructions": catalog.INSTRUCTION_EXAMPLES, "design": catalog.DESIGN_EXAMPLES},
            "/api/providers": hub.provider_list,
        }
        if p in routes:
            return self._run(routes[p])
        m = re.fullmatch(r"/(clips|samples)/([0-9a-f]{16})\.(wav|mp3|flac|opus|aac)", p)
        if m:
            f = (hub.CLIPS if m[1] == "clips" else hub.SAMPLES) / f"{m[2]}.wav"
            if not f.exists():
                return self.send_error(404)
            f = audio.convert(f, m[3])
            return self._file(f, audio.FORMATS[m[3]], {"Content-Disposition": f'inline; filename="vox-{m[2]}.{m[3]}"'})
        if p in ("/voices", "/playground", "/models", "/providers", "/api-docs") or p.startswith("/models/"):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/v1/audio/speech":
            return self._run(self._openai_speech, openai=True)
        routes = {
            "/api/speech": lambda b: self._speech_json(b),
            "/api/models/pull": lambda b: hub.pull(b.get("model", ""), background=True),
            "/api/models/load": lambda b: hub.load(b.get("model", "")),
            "/api/models/unload": lambda b: hub.unload(b.get("model", "")),
            "/api/voices/sample": lambda b: hub.sample(b.get("ref", "")),
            "/api/history/update": lambda b: (hub.update_history(b.get("id", ""), b.get("star"), bool(b.get("delete"))), {"ok": True})[1],
            "/api/asr": lambda b: {"id": b.get("id"), "text": hub.asr(b.get("id", ""))},
            "/api/my-voices": lambda b: hub.save_my_voice(b.get("name", "").strip() or "未命名音色", b.get("request", {}), b.get("id")),
            "/api/my-voices/delete": lambda b: (hub.delete_my_voice(b.get("id", "")), {"ok": True})[1],
            "/api/settings": lambda b: hub.set_settings(sample_text=b.get("sample_text"), favorites=b.get("favorites")),
            "/api/keys": lambda b: hub.set_key(b.get("env", ""), b.get("value", "")),
            "/api/keys/delete": lambda b: hub.delete_key(b.get("env", "")),
            "/api/voices/refresh": lambda b: {"model": b.get("model"), "count": hub.refresh_voices(b.get("model", ""))},
            "/api/estimate": lambda b: hub.estimate(hub.normalize(b)),
            "/api/providers/discover": lambda b: hub.discover(b.get("provider", "")),
            "/api/models/add": lambda b: hub.add_model(b.get("model"), b.get("provider"), b.get("remote"), b.get("name")),
            "/api/models/remove": lambda b: hub.remove_model(b.get("model", ""), bool(b.get("delete_files"))),
            "/api/registry/update": lambda b: hub.registry_update(b.get("url")),
            "/api/providers/add": lambda b: hub.provider_save(b.get("id", ""), b.get("config", {}), b.get("key"), bool(b.get("overwrite"))),
            "/api/providers/remove": lambda b: hub.provider_remove(b.get("id", "")),
            "/api/providers/test": lambda b: hub.provider_test(b.get("config"), b.get("id"), b.get("key")),
        }
        if p not in routes:
            return self.send_error(404)
        self._run(lambda: routes[p](self._body()))

    def _speech_json(self, b):
        rec = hub.speak(b, source=b.pop("source", "webui") if isinstance(b, dict) else "webui")
        return {**{k: v for k, v in rec.items() if k != "file"}, "url": f"/clips/{rec['id']}.wav"}

    def _openai_speech(self):
        b = self._body()
        fmt = b.pop("response_format", "mp3")
        b.pop("stream_format", None)
        if fmt not in audio.FORMATS:
            raise hub.VoxError(f"response_format 不支持 {fmt}，可选：{', '.join(audio.FORMATS)}")
        rec = hub.speak(b, source="api")
        f = audio.convert(Path(rec["file"]), fmt)
        self._file(f, audio.FORMATS[fmt], {"X-Vox-Id": rec["id"], "X-Vox-Seed": rec["request"].get("seed", ""), "X-Vox-Duration": rec["dur"]}, cache=False)


def _announce(host, port):
    """把地址写进数据目录的 server.json：同一份数据的 CLI 据此找到这个服务，数据目录不同的就找不到它。"""
    reach = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    paths.HOME.mkdir(parents=True, exist_ok=True)
    paths.SERVER_FILE.write_text(json.dumps({"url": f"http://{reach}:{port}", "pid": os.getpid(), "home": str(paths.HOME)}))


def _retract():
    try:
        if json.loads(paths.SERVER_FILE.read_text()).get("pid") == os.getpid():
            paths.SERVER_FILE.unlink()
    except (OSError, ValueError):
        pass


def serve(host="127.0.0.1", port=8765, open_browser=False):
    srv = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    _announce(host, port)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # kill 时也走 finally，清掉 server.json
    print(f"vox 已启动：{url}\n  WebUI  {url}\n  OpenAI 兼容  {url}v1/audio/speech\n  Agent 说明  {url}llms.txt\n  数据  {paths.HOME}\n  Ctrl+C 退出", flush=True)
    if open_browser:
        subprocess.Popen(["open", url])
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _retract()
