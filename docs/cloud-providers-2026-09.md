# 云端 TTS Provider 调研（2026-09-24）

两路并行调研（海外 / 国内），以官方文档为准；[核] 官方核实、[部分] 部分核实或二手、[未核] 未拿到依据。只读调研，未调用任何付费 API，**未做听感评测**。

## 总览

| Provider | 主力模型（精确 ID） | 形态 | 认证 | 情绪 / 风格控制 | 声音设计 | 克隆 | seed | 中文 | 价格（官方口径） |
|---|---|---|---|---|---|---|---|---|---|
| OpenAI [核] | `gpt-4o-mini-tts`（→ `-2025-12-15`）、`tts-1(-hd)` | OpenAI 基准 | Bearer | `instructions` 自然语言 | — | 限资格客户 | — | 列表内，未测 | 文本 $0.6/1M tok + 音频 $12/1M tok |
| Inworld [核] | `inworld-tts-2`、`inworld-tts-2-flash`（2026-08-31 GA） | **OpenAI 兼容** `api.inworld.ai/v1` | Bearer | `instructions`（需英文）+ 行内 `[say excitedly]` | 有 | 即时 + 专业 | — | 普通话 Tier1 | $5–25 / 1M 字符 |
| ElevenLabs [核] | `eleven_v3`、`eleven_flash_v2_5`、`eleven_multilingual_v2` | 私有 | `xi-api-key` | 行内标签 `[laughs]` + style 数值 | 有 | IVC + PVC | **有** | 支持 | v3 $0.10/1K 字符，Flash $0.05 |
| Google Gemini API [核] | `gemini-3.8-flash-tts`、`gemini-3.8-flash-lite-tts`（2026-09-23） | 私有（嵌套 JSON） | `x-goog-api-key` | 自然语言 `style` + `<cough>` 标签 | 有 | 有（需口头授权） | 未核 | 普通话 / 粤语 | 音频 $6–9 / 1M tok，有免费层，2027-01 起翻倍 |
| Azure Speech [核] | Neural / DragonHD；`MAI-Voice-2(-Flash)` 预览 | SSML | `Ocp-Apim-Subscription-Key` | `mstts:express-as style` 枚举（60+） | — | 受限申请 | — | **中文音色最多** | $15–22 / 1M 字符，免费 0.5M/月 |
| Cartesia [核] | `sonic-3.6` | 私有 | Bearer + `Cartesia-Version` | `emotion` 枚举 50+ | 未核 | 有 | — | 支持 | ≈$37–50 / 1M 字符 |
| Hume [核] | Octave 2（preview） | 私有 | `X-Hume-Api-Key` | `description` 自然语言 | 有（仅英文） | 有 | — | **无** | $0.10–0.15 / 1K 字符 |
| Fish Audio [核] | `s2.1-pro`、`s2.1-pro-free`（免费至 2026-11-30） | 私有，模型走 `model` header | Bearer | 行内自然语言 `[whispers sweetly]` | 有 | 有 | — | 强 | $15 / 1M **UTF-8 字节**（中文 ×3） |
| xAI [核] | 无模型 ID（2026-04） | 私有 | Bearer | 行内标签 | 未核 | 仅企业 / 美国 | — | 支持 | $15 / 1M 字符 |
| Mistral [核] | `voxtral-mini-tts-2603` | 近 OpenAI（`voice_id`、返回 base64） | Bearer | 靠参考音频 | — | 零样本 | — | **无** | $16 / 1M 字符 |
| Deepgram / Rime / Speechify / Murf / Polly / Resemble / Smallest / Soniox | 见海外原始报告 | 私有 | — | 大多无或枚举 | — | — | — | 多数无中文 | — |
| **阿里云百炼** [核] | `qwen-audio-3.0-tts-plus`（2026-07）、`cosyvoice-v3.5-plus/flash`、`qwen3-tts-flash`、`qwen3-tts-instruct-flash`、`qwen3-tts-vd` | DashScope 私有，**三套端点** | Bearer（Qwen-Audio / CosyVoice 另需 WorkspaceId） | `instruction(s)` 自然语言 + 标签 | 有 | 有 | **有** | 最强梯队 | 0.8–1.5 元 / 万字符 |
| **火山 豆包** [核] | `seed-tts-2.0`（standard / expressive）、`seed-icl-2.0` | 私有，HTTP chunked / SSE / WS，返回 base64 分块 | 新控制台 `X-Api-Key` + `X-Api-Resource-Id`；音色列表需 AK/SK 签名 | `[#用吵架的语气]` 行内指令 + `emotion` 枚举 + 上文 | 二手报道 | 有 | — | 最强梯队 | 3 元 / 万字符 |
| **MiniMax** [核] | `speech-2.8-hd`、`speech-2.8-turbo`（2026-01） | 私有 `/v1/t2a_v2`，默认 hex 音频 | Bearer | `emotion` 枚举 9 种 + 文本标签 | 有 `/v1/voice_design` | 有 | — | 强，≈327 音色 | hd 3.5 / turbo 2.0 元 / 万字符（汉字按 2 字符） |
| **阶跃 StepFun** [核] | `stepaudio-3-tts`（2026-09-15）、`stepaudio-2.5-tts` | **近 OpenAI** `/v1/audio/speech` | Bearer | `instruction` 自然语言（≤500 字） | 未核 | 3 秒零样本 | — | 强 | 2.5 元 / 万字符 |
| **小米 MiMo** [核] | `mimo-v2.5-tts`、`-voicedesign`、`-voiceclone`（2026-04） | OpenAI **chat/completions + audio** | Bearer / `api-key` | user 消息写风格指令 | 有 | 有（base64 参考音频） | — | 强，方言 | 限时免费 |
| **硅基流动** [核] | `FunAudioLLM/CosyVoice2-0.5B`、`fnlp/MOSS-TTSD-v0.5` | **OpenAI 兼容** | Bearer | 文本内标签 / `<\|endofprompt\|>` | — | 有 | — | 开源模型水平 | 0.05 元 / 千字节 |
| 智谱 [部分] | `glm-tts` | 近 OpenAI（路径 `/api/paas/v4/audio/speech`） | Bearer | 无显式字段 | 未核 | 有 | — | 支持 | 2 元 / 万字符 [未核] |
| ListenHub [部分] | `flowtts` | **OpenAI 兼容** | Bearer | 未核 | 未核 | 有 | — | 支持 | credits [未核] |
| 腾讯云 [核] | TextToVoice + VoiceType（超自然大模型音色） | 私有，TC3-HMAC 签名，单次 ≤150 字 | 签名 | `EmotionCategory` 枚举 | — | 独立产品 | — | 支持 | 0.3–6.5 元 / 万字符 |
| 百度 [部分] | `per` 编号 | 私有，access_token | Key+Secret 换 token | `text_ctrl` 枚举 | — | 有 | — | 支持 | 按次 / 资源包 |
| 讯飞 超拟人 [部分] | `vcn` 发音人 | **仅 WebSocket**，HMAC 签名，base64 文本 | 签名 | 无（口语化程度） | — | 有 | — | 支持 | 未核 |

**不接**：LMNT（已停服）、PlayHT（2025-12-31 关停）、Sesame（无公开 API）、Kimi（无 TTS API）、魔音工坊（仅企业）。
**聚合 / 托管平台**（以后做"聚合的聚合"）：fal.ai、Replicate、Together、DeepInfra（`Qwen/Qwen3-TTS`，OpenAI 兼容）、Groq。

## 统一接入要处理的差异

1. **seed**：只有 ElevenLabs、阿里百炼有；其余忽略，并在结果上标「不可复现」。
2. **instructions 四种落地方式**：原生自然语言（OpenAI、Inworld、Gemini、Hume、阿里、StepFun、MiMo）／改写成行内标签（ElevenLabs v3、Fish、xAI、火山 `[#…]`）／映射到枚举（Azure、Cartesia、MiniMax、腾讯、百度）／不支持。
3. **语速取值**：各家范围与方向不同（Rime 反向；火山 -50–100；腾讯 -2–6；百度 0–15），网关统一 0.25–4 倍后线性映射并裁剪。
4. **返回体**：裸音频／base64 JSON（Inworld 原生、Mistral、火山分块）／hex（MiniMax）／临时 URL（Qwen-TTS 非流式），统一解码成字节后走本地 ffmpeg 转格式。
5. **计费口径**：MiniMax 汉字 ×2；Fish、硅基流动按 UTF-8 字节（汉字 ×3）；StepFun 汉字 ×1。比价前先折算成「元 / 万汉字」。
6. **认证**：Bearer 占大多数；签名类（腾讯 TC3、火山音色列表、讯飞、Polly SigV4）成本高，放后面。

原始调研全文见本次会话；各家官方文档链接见上表对应 Provider 的官网文档。


## 补充（2026-09-24）：模型列表与 OpenRouter

- **不用 Key 就能拿到模型列表的**只有聚合平台：OpenRouter（`GET /api/v1/models?output_modalities=speech`，带 `supported_voices` 和 `pricing`）和 HuggingFace（`/api/models` 搜索）。10 家厂商的列表接口都要 Key（实测无 Key 返回 401 / 403；ElevenLabs 返回匿名工作区不存在）。
- **有 TTS 列表接口的厂商**：OpenAI、阶跃（`/v1/models`，无能力字段，按名字含 tts 识别）、硅基流动（`?type=audio`，再去掉语音识别模型）、ElevenLabs（`can_do_text_to_speech`）、Gemini（分页，按名字含 tts 识别）。阿里百炼、火山、MiniMax、小米、Inworld 查不到公开的 TTS 模型列表接口。
- **OpenRouter 语音接口**：`POST /api/v1/audio/speech`，OpenAI 兼容；字段 model / input / voice / response_format（mp3 或 pcm，默认 pcm）/ speed（各家支持不一）/ provider（透传）；没有 instructions。TTS 按输入字符计费。文档 https://openrouter.ai/docs/guides/overview/multimodal/tts
- 以上列表接口的过滤规则里，OpenAI / 阶跃 / Gemini 按名字识别是推断，拿到真 Key 后要核对。
