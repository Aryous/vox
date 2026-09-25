"""下载模型到 ~/.vox/models/<repo>（位置见 paths.py）。

文件清单和校验值（大文件 SHA256、小文件 git sha1）取自 HuggingFace 官方 API（权威来源）；文件本体可从 ModelScope 或 HuggingFace 下载，
下载后逐个校验大小和哈希，不一致就删掉重来。国内网络下 HuggingFace CDN 常只有几 KB/s，默认走 ModelScope。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import paths

ROOT = paths.MODELS
SOURCES = {
    "modelscope": "https://modelscope.cn/models/{repo}/resolve/master/{path}",
    "hf": "https://huggingface.co/{repo}/resolve/main/{path}",
}


def local_dir(repo: str) -> Path:
    return ROOT / repo


def is_ready(repo: str) -> bool:
    return (local_dir(repo) / ".vox-complete").exists()


def _manifest(repo: str):
    cache = local_dir(repo) / ".vox-manifest.json"
    if cache.exists():
        items = json.loads(cache.read_text())
    else:
        url = f"https://huggingface.co/api/models/{repo}/tree/main?recursive=true"
        for attempt in range(5):  # 访问 HuggingFace 常有 SSL 中断，重试几次
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    items = json.load(r)
                break
            except OSError as e:
                if attempt == 4:
                    raise SystemExit(f"获取文件清单失败：{e}")
                time.sleep(2 * (attempt + 1))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(items))
    skip = {".gitattributes", "README.md"}
    # 校验值：LFS 大文件用 sha256，普通小文件用 git blob sha1（HuggingFace API 的 oid）
    return [(x["path"], x["size"], ("sha256", x["lfs"]["oid"]) if x.get("lfs") else ("git", x["oid"]))
            for x in items if x["type"] == "file" and x["path"] not in skip]


def _digest(p: Path, kind: str) -> str:
    h = hashlib.sha256() if kind == "sha256" else hashlib.sha1(f"blob {p.stat().st_size}\0".encode())
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(repo: str, source: str = "modelscope") -> Path:
    dest = local_dir(repo)
    if is_ready(repo):
        print(f"✓ 已存在 {dest}", file=sys.stderr)
        return dest
    paths.ensure_models_dir()
    files = _manifest(repo)
    total = sum(s for _, s, _ in files)
    print(f"{repo}：{len(files)} 个文件，{total / 1e9:.2f} GB，来源 {source}（哈希以 HuggingFace 为准）", file=sys.stderr)
    for path, size, oid in files:
        out = dest / path
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists() and out.stat().st_size == size and _digest(out, oid[0]) == oid[1]:
            continue
        url = SOURCES[source].format(repo=repo, path=path)
        print(f"↓ {path}  {size / 1e6:.1f} MB", file=sys.stderr)
        # curl：-C - 断点续传，--retry 应对抖动；进度条输出到 stderr
        subprocess.run(["curl", "-L", "--fail", "--retry", "5", "-C", "-", "-o", str(out), url] + ([] if size > 5e6 else ["-s"]), check=True)
        if out.stat().st_size != size or _digest(out, oid[0]) != oid[1]:
            out.unlink()
            raise SystemExit(f"✗ 校验失败：{path}（已删除，重跑 vox fetch 会重新下载）")
    (dest / ".vox-complete").write_text(json.dumps({"repo": repo, "source": source}))
    print(f"✓ 校验通过，模型在 {dest}", file=sys.stderr)
    return dest
