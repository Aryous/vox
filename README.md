# vox

本地 TTS 的统一入口：像 LM Studio 管理大模型一样管理 TTS 模型，像 OpenRouter 一样用一套接口调用它们。

- **引擎层**：本地模型的发现、下载、加载、卸载，外加 OpenRouter 和 10 家云端 Provider；OpenAI 兼容的 `POST /v1/audio/speech`，任何 OpenAI 客户端改个 base URL 就能用。
- **展示层**：音色库（所有模型的所有音色，读同一段样本，点开就听）、试音台（自由调参、A/B 对比、读音校对）。
- **人和 Agent 同等**：CLI、HTTP、WebUI 用同一套模型 ID、音色引用和参数名；CLI 全部支持 `--json`，服务提供 `/llms.txt`。

| 来源 | 模型 |
| --- | --- |
| 本地 | `local/qwen3`（Qwen3-TTS CustomVoice）、`local/qwen3-design`（VoiceDesign）、`local/kokoro`；另可从 HuggingFace 查到 Qwen3-TTS 的 0.6B / 1.7B 各量化版本 |
| 聚合 | OpenRouter：一个 Key 调用它的全部 TTS 模型（Fish Audio、MAI-Voice、Grok Voice、Deepgram Aura 等，列表在线获取） |
| 海外云端 | OpenAI `gpt-4o-mini-tts` · Inworld `inworld-tts-2(-flash)` · ElevenLabs `eleven_v3` / `eleven_flash_v2_5` / `eleven_multilingual_v2` · Google `gemini-3.8-flash(-lite)-tts` |
| 国内云端 | 阿里云百炼 `qwen-audio-3.0-tts-plus` / `cosyvoice-v3-flash` / `qwen3-tts(-instruct)-flash` · 火山豆包 `seed-tts-2.0` · MiniMax `speech-2.8-hd/turbo` · 阶跃 `stepaudio-3-tts` / `2.5` · 硅基流动 CosyVoice2 · 小米 `mimo-v2.5-tts(-voicedesign)` |

`vox models` 列出我的模型，`vox models --all` 列出全部；各家接入细节与官方文档出处见 `docs/cloud-providers-2026-09.md`。

## 安装

```bash
cd ~/Documents/Code/p-vox
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e .
ln -sf "$PWD/.venv/bin/vox" ~/.local/bin/vox
vox models add qwen3  # 下载模型：默认走 ModelScope，逐个文件按 HuggingFace 哈希校验
vox serve --open      # http://127.0.0.1:8765
```

需要 Apple Silicon（MLX）和 ffmpeg；读音校对需要本机 `coli`（`npm i -g @marswave/coli`），没有也能用，只是少了这项功能。

## 统一的名字

| | CLI | HTTP（JSON） | WebUI |
| --- | --- | --- | --- |
| 模型 | `-m qwen3` | `model: "local/qwen3"`（短名也行） | 模型 |
| 音色 | `-v serena` / `-v qwen3:serena` / `-v my:<id>` | `voice` | 音色 |
| 情绪 / 声音描述 | `-i "轻快友好"` | `instructions` | 情绪 / 语气 |
| 语速 | `-s 1.1` | `speed`（0.25–4） | 语速 |
| 种子 | `--seed 42` | `seed`（vox 扩展） | 随机种子 |
| 采样 | `--temperature` `--top-p` `--top-k` `--repetition-penalty` | 同名 | 更多设置 |

音色引用：`模型短名:音色`（如 `kokoro:zf_003`），自定义音色是 `my:<id>`（保存的是模型 + 音色 + 情绪 + 种子的组合）。

## CLI

```bash
vox models                         # 我的模型（--all 含未下载 / 未连接的；-p gemini 只看一家；--json 给 Agent）
vox models fetch openrouter        # 在线查询这家现在提供的模型（local = HuggingFace）
vox models add qwen3-design        # 加进我的模型：本地 = 下载，云端 = 加入清单；没登记的写 provider/模型名
vox models rm <模型 ID>             # 移出我的模型（本地要加 --delete-files，会删除模型文件）
vox models update                  # 拉取新版模型注册表
vox load qwen3 / vox unload qwen3  # 作用于运行中的服务
vox voices -m qwen3 --gender 女    # 音色库
vox sample qwen3:serena --play     # 试听音色样本
vox say "你好" -m qwen3 -v serena -i "轻快友好" -o hi.mp3 --play
echo "从标准输入读" | vox say - -v kokoro:zm_010
vox history --star                 # 历史（与 WebUI 共享）
vox status
vox batch script.json -o vo/       # 多角色脚本批量合成，只重做改过的句子
```

服务在运行时，`say / sample / load / unload` 自动交给服务执行，直接用内存里已加载的模型；`--local` 强制在本进程合成。

## HTTP

```bash
curl http://127.0.0.1:8765/v1/audio/speech -H "Content-Type: application/json" \
  -d '{"model":"local/qwen3","input":"你好","voice":"serena","instructions":"轻快友好","seed":42,"response_format":"mp3"}' -o hi.mp3
```

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8765/v1", api_key="vox")
with client.audio.speech.with_streaming_response.create(
    model="local/qwen3", voice="serena", input="你好", instructions="轻快友好", extra_body={"seed": 42}
) as r:
    r.stream_to_file("hi.mp3")
```

响应头带 `X-Vox-Id`、`X-Vox-Seed`、`X-Vox-Duration`。原生 JSON 接口（`/api/models`、`/api/voices`、`/api/speech`、`/api/history`…）见 WebUI 的 API 页或 `GET /llms.txt`。

## 脚本格式（vox batch）

```json
{
  "defaults": {"model": "qwen3"},
  "voices": {
    "N": {"voice": "uncle_fu", "instructions": "沉稳的纪录片旁白"},
    "C": {"voice": "my:narrator"},
    "L": {"model": "kokoro", "voice": "zm_010", "speed": 1.1}
  },
  "lines": [
    {"id": "intro", "who": "N", "s": "屏幕上显示的文字", "v": "可选：实际朗读的文字"},
    {"who": "C", "s": "单句也可以覆盖 instructions", "instructions": "有点心虚"}
  ]
}
```

也支持 `scenes[].lines`（文件命名 `sXX_YY`，并输出网页可直接加载的 `timing.js`）。旧脚本里的 `engine` / `instruct` 仍然兼容。

## 云端 Provider 与 Key

```bash
vox keys list                    # 每家需要哪些凭证、是否已配置、去哪申请
vox keys set MINIMAX_API_KEY     # 交互输入，不回显，不进 shell 历史
echo "$KEY" | vox keys set OPENAI_API_KEY
vox keys rm OPENAI_API_KEY
```

- **读取顺序：环境变量 > 本地配置文件**（`~/.config/vox/credentials.json`，权限 600，路径可用 `VOX_CONFIG` 改）。终端、脚本、Agent 用环境变量；日常在 WebUI「模型」页选中这家后粘贴即可。
- Key 不会经 API 返回，也不写日志；界面只显示来源和末 4 位。
- 可选配置：`OPENAI_BASE_URL`（代理）、`MINIMAX_BASE_URL` / `STEPFUN_BASE_URL` / `SILICONFLOW_BASE_URL`（国际站）、`DASHSCOPE_WORKSPACE_ID`（阿里专属域名）。
- 统一层会处理各家差异：指令字段名（`instructions` / `instruction` / 写进正文 / 音频标签 / 情绪枚举）、语速范围、返回体（裸字节、base64、hex、临时 URL、分块流）。
- **种子**：只有 ElevenLabs 和阿里百炼部分模型支持；其余云端结果标记「不可复现」。
- **费用**：每条云端结果按官方单价估算（按 token 计费的只给价格说明）；同样的请求命中本地缓存，不重复付费。音色样本只在点击时生成。

### Provider 与模型

Provider 只管连接（Key、地址），模型是另一回事。两件事分开判断：

- **能不能用**是系统事实，不给开关：本地模型下没下载、云端 Provider 连没连上（有没有 Key）。
- **我的模型**是用户选择：能用的模型里你留下的那些。音色库、试音台、`/v1/models` 只用它们。
  - 本地：下载了就在我的模型里；移除 = 删除模型文件（WebUI 原地二次确认，CLI 要 `--delete-files`）。
  - 云端：连接后默认带上注册表推荐的模型；再从在线列表添加、手动填模型 ID，或移除。
- **可添加**的模型来自在线列表：OpenAI、阶跃、硅基流动、ElevenLabs、Gemini 用各家的列表接口（要 Key），OpenRouter 和 HuggingFace 是公开接口（不用 Key 也能浏览）。阿里百炼、火山、MiniMax、小米、Inworld 没有公开的列表接口，只能手动填 ID。
- 注册表里没有的模型，借用同一家已核对模型的请求格式，只换模型名；界面上标「能力推断」，价格请看官网。

### 数据与代码分开

- **代码**（`vox/providers/`、`vox/engines.py`）只负责怎么调用：每家的请求怎么拼、响应怎么解析。
- **数据**（`vox/registry.json`）负责有什么：Provider 的连接方式与适配器配置、核对过的模型元数据（能力、价格、音色）。它随包发布，`vox models update` 可以拉新版（日期更新才生效；需要这个版本没有的适配器时提示升级 vox）。默认地址是本仓库的 `vox/registry.json`，可用 `VOX_REGISTRY_URL` 改。
- 在线列表的结果缓存在 `$VOX_HOME/discovered/`，我的模型记在 `$VOX_HOME/models.json`。

### 新增一家 Provider

1. `vox/providers/` 下写一个 `CloudEngine` 子类，实现 `synth(req) -> (音频字节, 格式)`，可选 `fetch_voices()`；OpenAI 兼容的直接用 `openai_compat`，只写配置。在线列表的新查询方式加在 `vox/discovery.py`。
2. 在 `vox/registry.json` 的 `providers` 登记凭证、控制台、文档、图标、适配器配置，以及在线列表怎么查（`discover`）；在 `models` 登记核对过的模型、能力、价格、静态音色（`voice_sets`）。
3. 在 `tests/test_providers.py` 按官方示例加一条离线测试。CLI、HTTP、WebUI 不需要改。

## 测试

```bash
.venv/bin/python tests/test_providers.py   # 31 项离线测试（约 1 秒）：拦截网络，按官方示例验证每家请求与响应解析、在线发现、我的模型、注册表更新
```

## 致谢

Provider 图标来自 [LobeHub Icons](https://github.com/lobehub/lobe-icons)（MIT，见 `vox/web/icons/LICENSE-lobe-icons.txt`）。

## 数据与卸载

数据都在 `$VOX_HOME`（默认 `~/.cache/vox`）：`models/` 模型、`clips/` 合成结果、`samples/` 音色样本、`history.json`、`my_voices.json`、`settings.json`、`models.json`（我的模型）、`discovered/`（在线列表缓存）、`voices/`（云端音色列表缓存）。Kokoro 模型在 `~/.cache/huggingface/hub/models--hexgrad--Kokoro-82M-v1.1-zh`。

卸载：删除本目录、`~/.local/bin/vox`，以及上面两个数据目录。
