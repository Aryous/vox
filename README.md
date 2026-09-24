# vox

本地 TTS 的统一入口：像 LM Studio 管理大模型一样管理 TTS 模型，像 OpenRouter 一样用一套接口调用它们。

- **引擎层**：本地模型的下载、加载、卸载，外加 10 家云端 Provider；OpenAI 兼容的 `POST /v1/audio/speech`，任何 OpenAI 客户端改个 base URL 就能用。
- **展示层**：音色库（所有模型的所有音色，读同一段样本，点开就听）、试音台（自由调参、A/B 对比、读音校对）。
- **人和 Agent 同等**：CLI、HTTP、WebUI 用同一套模型 ID、音色引用和参数名；CLI 全部支持 `--json`，服务提供 `/llms.txt`。

| 来源 | 模型 |
| --- | --- |
| 本地 | `local/qwen3`（Qwen3-TTS CustomVoice）、`local/qwen3-design`（VoiceDesign）、`local/kokoro` |
| 海外云端 | OpenAI `gpt-4o-mini-tts` · Inworld `inworld-tts-2(-flash)` · ElevenLabs `eleven_v3` / `eleven_flash_v2_5` / `eleven_multilingual_v2` · Google `gemini-3.8-flash(-lite)-tts` |
| 国内云端 | 阿里云百炼 `qwen-audio-3.0-tts-plus` / `cosyvoice-v3-flash` / `qwen3-tts(-instruct)-flash` · 火山豆包 `seed-tts-2.0` · MiniMax `speech-2.8-hd/turbo` · 阶跃 `stepaudio-3-tts` / `2.5` · 硅基流动 CosyVoice2 · 小米 `mimo-v2.5-tts(-voicedesign)` |

`vox models` 列出全部模型与状态；各家接入细节与官方文档出处见 `docs/cloud-providers-2026-09.md`。

## 安装

```bash
cd ~/Documents/Code/p-vox
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e .
ln -sf "$PWD/.venv/bin/vox" ~/.local/bin/vox
vox pull qwen3        # 下载模型：默认走 ModelScope，逐个文件按 HuggingFace 哈希校验
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
vox models                         # 模型清单与状态（--json 给 Agent；-p gemini 只看一家）
vox models fetch gemini            # 向 Provider 获取它现在提供的 TTS 模型
vox models add gemini/<模型名>      # 加进清单；vox models off / on / rm <模型 ID> 停用、启用、删除
vox pull qwen3-design              # 下载
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

Provider 只管连接（Key、地址），模型是清单里的条目，两者分开管理。WebUI 的「模型」页左边是 Provider，右边是它的模型：

- vox 为每家预置了经过核对的模型（价格、能力、音色都已登记），默认启用；停用的模型不出现在音色库和试音台，但 API 仍可直接调用。
- **获取模型列表**：OpenAI、阶跃、硅基流动、ElevenLabs、Gemini 有官方的模型列表接口，配好 Key 后可以查询这家现在提供的 TTS 模型，一键加进清单。阿里百炼、火山、MiniMax、小米、Inworld 没有公开的列表接口，用「手动添加」填模型 ID。
- 新加的模型借用同一家预置模型的请求格式，只换模型名；能力按同家推断，价格需自行查看官网。清单设置保存在 `$VOX_HOME/models.json`。

### 新增一家 Provider

1. `vox/providers/` 下写一个 `CloudEngine` 子类，实现 `synth(req) -> (音频字节, 格式)`，可选 `fetch_voices()`、`list_models()`；OpenAI 兼容的直接用 `openai_compat`，只写配置。
2. 在 `vox/catalog.py` 的 `PROVIDERS` 登记凭证、控制台、文档、图标；在 `vox/cloud_catalog.py` 登记模型、能力、价格、静态音色。
3. 在 `tests/test_providers.py` 按官方示例加一条离线测试。CLI、HTTP、WebUI 不需要改。

## 测试

```bash
.venv/bin/python tests/test_providers.py   # 24 项离线测试：拦截网络，按官方示例验证每家请求与响应解析
```

## 致谢

Provider 图标来自 [LobeHub Icons](https://github.com/lobehub/lobe-icons)（MIT，见 `vox/web/icons/LICENSE-lobe-icons.txt`）。

## 数据与卸载

数据都在 `$VOX_HOME`（默认 `~/.cache/vox`）：`models/` 模型、`clips/` 合成结果、`samples/` 音色样本、`history.json`、`my_voices.json`、`settings.json`、`models.json`。Kokoro 模型在 `~/.cache/huggingface/hub/models--hexgrad--Kokoro-82M-v1.1-zh`。

卸载：删除本目录、`~/.local/bin/vox`，以及上面两个数据目录。
