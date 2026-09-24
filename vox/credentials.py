"""云端 Provider 的凭证。

读取顺序：环境变量 > 本地配置文件（$VOX_CONFIG，默认 ~/.config/vox/credentials.json，权限 600）。
- 环境变量适合终端、脚本、CI、Agent；配置文件适合在 WebUI 里粘贴。
- 凭证不会经 API 返回，也不写日志；对外只暴露「是否已配置、来源、末 4 位」。

一个 Provider 可能需要多个字段（如阿里的 API Key + Workspace），每个字段对应一个环境变量名。
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

PATH = Path(os.environ.get("VOX_CONFIG", Path.home() / ".config" / "vox")) / "credentials.json"


def _read() -> dict:
    try:
        return json.loads(PATH.read_text())
    except Exception:
        return {}


def _write(data: dict):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 600：只有当前用户可读写
    tmp.replace(PATH)


def get(env: str) -> str | None:
    """按环境变量名取值：先环境变量，再配置文件。"""
    return os.environ.get(env) or _read().get(env) or None


def source(env: str) -> str | None:
    if os.environ.get(env):
        return "env"
    if _read().get(env):
        return "file"
    return None


def set(env: str, value: str):
    data = _read()
    data[env] = value.strip()
    _write(data)


def delete(env: str):
    data = _read()
    data.pop(env, None)
    _write(data)


def status(env: str) -> dict:
    v = get(env)
    return {"env": env, "configured": bool(v), "source": source(env), "last4": v[-4:] if v and len(v) >= 8 else None}
