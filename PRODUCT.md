# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- 通用、偏 geek 的用户：想知道「各个 TTS 模型、各个音色到底听起来怎么样」，并在本地把 TTS 当基础设施来用的人。
- Agent：通过 CLI（`--json`）或 HTTP API 调用语音合成、查询模型与音色。人和 Agent 是同等重要的使用者。
- 按开源产品标准设计：第一次打开的陌生人也要能自己走通。

## Product Purpose

vox 是 TTS 领域的 LM Studio / OpenRouter：

- **引擎层**：统一管理多个 TTS 模型（发现、下载、加载、卸载），用一套统一的请求格式调用任意模型；对外提供 OpenAI 兼容的 `/v1/audio/speech` 接口。
- **展示层**：把所有模型的所有音色摊开，用同一句标准文本试听，公平地横向比较；在试音台里自由调参；对比模式里同一段文本比较多个音色、模型或语气（候选清单、统一种子、按需生成、费用预估）。

成功的标志：几分钟内听遍所有音色、找到想要的声音；任何应用或 Agent 改一个 base URL 就能用上本地任何模型。

## Positioning

- 统一：一个模型 ID + 一个音色 ID + 同名参数（`model` / `voice` / `instructions` / `speed`），跨引擎、跨 CLI / API / WebUI 一致。
- 本地优先：模型下载后离线运行；云端提供方作为可选接入（第二期），与本地模型走同一接口。
- 公平试听：同一标准文本生成的音色样本，支持读音校对（本地 ASR）。

## Operating Context

- `vox serve` 启动本地服务（默认 127.0.0.1:8765），同时承载 WebUI、原生 API（`/api/*`）和 OpenAI 兼容 API（`/v1/*`）。
- CLI 与服务共用同一个核心库与数据目录（`~/.cache/vox`）：历史、收藏、样本、模型文件共享。
- 模型下载默认走 ModelScope，按 HuggingFace 哈希校验。

## Capabilities and Constraints

- 本地：`kokoro`（Kokoro-82M-zh）、`qwen3`（Qwen3-TTS CustomVoice）、`qwen3-design`（VoiceDesign）；HuggingFace 上 Qwen3-TTS 的其他尺寸、量化版本可在线查到并下载，用同一引擎运行。
- 云端：OpenRouter（聚合）+ 10 家 Provider（OpenAI、Inworld、ElevenLabs、Gemini、阿里百炼、火山豆包、MiniMax、阶跃、硅基流动、小米 MiMo）。Key 读环境变量或 `~/.config/vox/credentials.json`，环境变量优先。
- 「能不能用」是系统事实（下没下载、连没连上），不做成开关；「我的模型」是用户在能用的模型里留下的那些，音色库、试音台、`/v1/models` 只用它们。
- 数据与代码分开：模型元数据在 `vox/registry.json`（可在线更新），新模型优先来自各家在线列表；代码只负责怎么调用。
- 模型能力各不相同（预置音色、情绪指令、声音设计、原生语速、随机种子），UI 与 CLI 按能力显示参数，不对不支持的参数撒谎。
- 需要 Apple Silicon（MLX）和 ffmpeg；读音校对依赖本机 `coli asr`，缺失时降级提示。
- 选角 / 批量合成属于工作流，保留在 CLI（`vox batch`），不进入 WebUI 主导航。

## Evidence on Hand

- 没有用户数量、评价或性能基准，不得编造。

## Product Principles

1. 一套词汇：模型、音色、参数在 CLI、API、WebUI 中同名同义。
2. 先听见：打开就能点播音色样本，不需要先懂参数。
3. 按能力呈现：只显示当前模型真正支持的控制项。
4. 可复现：每条结果记录完整请求（含种子），可复制为 CLI 命令或 API 请求。
5. 人和 Agent 同等：每个页面的操作都有对应的 CLI / API 等价物，并在界面上可见。
6. 不写死清单：能在线查到的（模型列表、音色、价格）就在线查，注册表只补接口给不了的信息，并作为离线兜底。
