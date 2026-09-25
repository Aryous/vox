"""vox 的文件放在哪里：只在这里决定，其他模块都从这里取路径。

按「丢了能不能找回」分四类：

  数据  ~/.vox                        合成结果 clips/、音色样本 samples/、history.json、my_voices.json、
                                      settings.json、models.json（我的模型）。丢了找不回来，要进备份。
  模型  ~/.vox/models                 下载的本地模型。能重新下载，所以标记为不进 Time Machine 备份。
  缓存  ~/Library/Caches/vox（macOS）  在线模型列表、云端音色列表、拉到的新版注册表。删了会自动重新获取，
        $XDG_CACHE_HOME/vox（其他）    清理工具清掉也没关系。
  凭证  ~/.config/vox/credentials.json（权限 600）。环境变量优先于这个文件，见 credentials.py。

为什么是 ~/.vox 而不是 ~/Library/Application Support：数据要被 CLI、本地服务、Agent 和将来的 App 共用，
和 Codex（~/.codex）、LM Studio（~/.lmstudio）、Ollama（~/.ollama）同一做法；路径短、没有空格、Linux 上一致。
将来的桌面 App 自己的内部状态（窗口、WebView 存储）才放 Application Support。

环境变量：
  VOX_HOME    把数据挪到别处；没单独指定时，模型和缓存也一起放进去（便携模式，测试也用它）
  VOX_MODELS  单独指定模型目录
  VOX_CACHE   单独指定缓存目录
  VOX_CONFIG  凭证所在目录
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_home_env = os.environ.get("VOX_HOME")
HOME = Path(_home_env).expanduser() if _home_env else Path.home() / ".vox"
MODELS = Path(os.environ["VOX_MODELS"]).expanduser() if os.environ.get("VOX_MODELS") else HOME / "models"

if os.environ.get("VOX_CACHE"):
    CACHE = Path(os.environ["VOX_CACHE"]).expanduser()
elif _home_env:
    CACHE = HOME / "cache"
elif sys.platform == "darwin":
    CACHE = Path.home() / "Library" / "Caches" / "vox"
else:
    CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "vox"

CONFIG = Path(os.environ.get("VOX_CONFIG", Path.home() / ".config" / "vox")).expanduser()

# 数据
CLIPS = HOME / "clips"
SAMPLES = HOME / "samples"
HISTORY = HOME / "history.json"
MY_VOICES = HOME / "my_voices.json"
SETTINGS = HOME / "settings.json"
MY_MODELS = HOME / "models.json"

# 缓存
DISCOVERED = CACHE / "discovered"
VOICE_LISTS = CACHE / "voices"
REGISTRY_UPDATE = CACHE / "registry.json"
KOKORO_VOICES = CACHE / "kokoro-voices.json"

# 凭证
CREDENTIALS = CONFIG / "credentials.json"


def ensure_models_dir() -> Path:
    """创建模型目录；在 macOS 上顺带把它排除出 Time Machine 备份（几 GB、能重新下载）。只做一次，失败不影响使用。"""
    first = not MODELS.exists()
    MODELS.mkdir(parents=True, exist_ok=True)
    if first and sys.platform == "darwin":
        subprocess.run(["tmutil", "addexclusion", str(MODELS)], capture_output=True)
    return MODELS


def summary() -> dict:
    return {"home": str(HOME), "models": str(MODELS), "cache": str(CACHE), "credentials": str(CREDENTIALS)}
