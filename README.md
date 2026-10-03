# vox

**One interface for speech models — text-to-speech and speech-to-text, local and cloud.**
Manage voice models the way LM Studio manages LLMs, and call any of them through one API the way OpenRouter does.

English · [中文](README.zh-CN.md)

> **Preview (0.1).** Works day-to-day on the author's Mac, but expect rough edges. The web UI and CLI messages are currently **Chinese only**; an English UI is planned. Local models need **macOS on Apple Silicon**.

![Compare mode: one text, one shared set of settings, several voices side by side, plus a variant of A with its own tone](docs/images/compare.png)

## What it does

- **One vocabulary everywhere.** The CLI, the HTTP API and the web UI use the same model IDs, voice references and parameter names (`model`, `voice`, `instructions`, `speed`, `seed`). Every CLI command supports `--json`, and the server publishes `/llms.txt`, so agents can drive it as easily as people.
- **OpenAI-compatible.** `POST /v1/audio/speech` — point any OpenAI client at `http://127.0.0.1:8765/v1` and it can use every model you have.
- **Local models, offline.** Qwen3-TTS (CustomVoice and VoiceDesign, every size and quantization published by `mlx-community`) and Kokoro-82M (Chinese). Downloads are verified file by file against HuggingFace hashes.
- **Cloud providers, same interface.** OpenRouter plus ten providers (list below). Per-provider quirks — where the emotion prompt goes, speed ranges, base64/hex/URL/chunked audio — are handled by adapters so you don't have to.
- **Custom providers.** Plug in any OpenAI-compatible speech service: a self-hosted Kokoro-FastAPI, a proxy, a vendor vox doesn't know yet, or another vox.
- **Speech-to-text, same model system.** `vox transcribe meeting.m4a` turns audio or video into text or subtitles (txt / srt / vtt / json) with local models (Qwen3-ASR, MOSS-Transcribe-Diarize, SenseVoice, Fun-ASR, Whisper — all through MLX) or cloud ones; OpenAI-compatible `POST /v1/audio/transcriptions`; a Transcribe page in the web UI. Speaker labels and word timestamps where the model supports them — locally, MOSS labels speakers and sentence timings in one pass, good for meetings, interviews and doctor visits.
- **Hear before you choose.** A voice library where every voice reads the same sample line; a playground with a compare mode: one text, one shared set of tone / speed / seed, and a list of voices or models generated side by side in one click (cost estimate first). Want to tweak one of them? Make a variant of it and compare the two.

| Voice library | Models and providers |
| --- | --- |
| ![Voice library](docs/images/voices.png) | ![Models page](docs/images/models.png) |

## Requirements

- macOS on Apple Silicon for local models (they run on [MLX](https://github.com/ml-explore/mlx)). Cloud and custom providers are plain HTTP, but only macOS is tested.
- Python 3.10+ (3.12 recommended) and [uv](https://docs.astral.sh/uv/).
- `ffmpeg` (`brew install ffmpeg`) for format conversion and speed changes.
- The pronunciation check uses a local speech-to-text model (for example `vox models add qwen3-asr`); [`coli`](https://www.npmjs.com/package/@marswave/coli) still works as a fallback.

## Install

```bash
uv tool install --python 3.12 git+https://github.com/Aryous/vox
vox serve --open            # web UI at http://127.0.0.1:8765
```

The package is called `vox-tts`; the command is `vox`.

For development:

```bash
git clone https://github.com/Aryous/vox && cd vox
uv venv --python 3.12 && uv pip install -e .
.venv/bin/python tests/test_providers.py     # 39 offline tests, ~1 s
```

## Quick start

```bash
vox models --all                          # everything vox knows about, and what's usable now
vox models add qwen3                      # download Qwen3-TTS CustomVoice 1.7B (≈3 GB)
vox say "Hello from vox." -m qwen3 -v ryan -o hello.mp3 --play
vox say "今天天气不错。" -m qwen3 -v serena -i "cheerful" --seed 42 --play
vox voices -m qwen3                       # voices of a model
vox models add qwen3-asr                  # local speech-to-text (Qwen3-ASR 0.6B, ≈1 GB)
vox models add moss                       # local speech-to-text with speaker labels (MOSS-Transcribe-Diarize 0.9B, ≈1.3 GB)
vox transcribe meeting.m4a -o meeting.txt # audio / video → text; -o talk.srt for subtitles (needs a model with timestamps)
vox serve --open                          # web UI + API
```

Kokoro downloads itself (~330 MB) the first time you use it. Qwen3 downloads go through the ModelScope mirror by default (much faster from mainland China) and are checked against HuggingFace hashes; `vox pull qwen3 --source hf` downloads from HuggingFace directly.

### From any OpenAI client

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8765/v1", api_key="vox")  # the local server ignores the key
with client.audio.speech.with_streaming_response.create(
    model="local/qwen3", voice="serena", input="Hello!", instructions="warm and calm",
    extra_body={"seed": 42},              # vox extension: reproducible takes
) as r:
    r.stream_to_file("hello.mp3")
```

Identical requests return the cached take; pass `cache: false` (CLI `--no-cache`) to synthesize again — useful for cloud models that have no seed. Responses carry `X-Vox-Id`, `X-Vox-Seed` and `X-Vox-Duration` headers. The native JSON API (`/api/models`, `/api/voices`, `/api/speech`, …) is listed on the web UI's API page and in `GET /llms.txt`.

## Models and providers

**My models** are the models you can use right now: downloaded local models, plus the models you've added from connected providers. The voice library, the playground and `/v1/models` only show these. Whether a model *can* be used (downloaded? key configured?) is a fact vox checks, not a switch you flip.

| Source | Models | Status |
| --- | --- | --- |
| Local | Qwen3-TTS CustomVoice / VoiceDesign (0.6B–1.7B, 4-bit to bf16), Kokoro-82M-zh | ✅ tested |
| OpenRouter | its whole TTS catalogue (Fish Audio, MAI-Voice, Grok Voice, Deepgram Aura, …), fetched live — browsable without a key | model list ✅ · synthesis ⚠️ |
| Google Gemini | `gemini-3.8-flash-tts`, `gemini-3.8-flash-lite-tts` | ✅ tested with a real key |
| OpenAI, Inworld, ElevenLabs | `gpt-4o-mini-tts`, `inworld-tts-2(-flash)`, `eleven_v3` / `flash_v2_5` / `multilingual_v2` | ⚠️ experimental |
| Alibaba Model Studio, Volcengine Doubao, MiniMax, StepFun, SiliconFlow, Xiaomi MiMo | Qwen-Audio / CosyVoice / Qwen3-TTS (cloud), Seed-TTS 2.0, Speech 2.8, StepAudio, CosyVoice2, MiMo TTS | ⚠️ experimental |
| Custom | any OpenAI-compatible speech service | ✅ tested (self-hosted, no key) |

⚠️ **Experimental** means the adapter is written from the provider's official docs and covered by offline tests that replay the documented requests and responses, and the real endpoint answered a deliberately invalid key with an authentication error — but it hasn't been run with a real key yet. If you have one, please try it and open an issue either way.

Where a provider publishes a model list, `vox models fetch <provider>` (or "在线查询" in the UI) pulls the current list. Models that aren't in vox's registry borrow the request format of a known model from the same provider and are marked as *inferred*.

### Keys

```bash
vox keys list                     # what each provider needs, what's configured, where to get a key
vox keys set GEMINI_API_KEY       # prompted, not echoed, not in shell history
```

Environment variables win over the credentials file (`~/.config/vox/credentials.json`, mode 600). Keys are never returned by the API or written to logs; the UI shows only the last four characters.

### Custom providers

```bash
vox providers add my-kokoro --base-url http://127.0.0.1:8880/v1 --no-key --instructions none
vox providers test my-kokoro      # checks {base}/models and {base}/audio/voices
vox models -p my-kokoro --all && vox models add my-kokoro/kokoro
```

vox calls `POST {base}/audio/speech`, reads models from `GET {base}/models` and voices from `GET {base}/audio/voices` (or a list you type in). Compatibility options cover where the emotion prompt goes and whether the service accepts `speed` (if not, vox changes speed with ffmpeg). vox itself serves `GET /v1/audio/voices`, so one vox can use another as a provider. In the web UI: Models → 添加 Provider.

## Names

| | CLI | HTTP | Example |
| --- | --- | --- | --- |
| Model | `-m` | `model` | `local/qwen3`, `qwen3`, `gemini/gemini-3.8-flash-tts` |
| Voice | `-v` | `voice` | `serena`, or a reference that carries the model: `qwen3:serena`, `my:<id>` |
| Emotion / voice description | `-i` | `instructions` | `"cheerful"`; for VoiceDesign models, a description of the voice |
| Speed | `-s` | `speed` | `0.25`–`4` |
| Seed | `--seed` | `seed` | reproducible takes on models that support it |
| Language hint (STT) | `-l` | `language` | `zh`, `en`; empty = auto-detect |
| Hotwords / context (STT) | `--hotwords` / `--prompt` | `hotwords` / `prompt` | sent only to models that support them |
| Speakers / word timings (STT) | `--diarize` / `--words` | `diarize` / `words` | an error, not a silent no-op, on models that can't |

## CLI

| Command | What it does |
| --- | --- |
| `vox models [--all] [-p provider]` | my models (or everything) and their status |
| `vox models fetch / add / rm / update` | query a provider's live list · add to my models (downloads local models) · remove (`--delete-files` for local) · update the registry |
| `vox pull <model>` | download a local model in the foreground |
| `vox load / unload <model>` | preload into / free from the running server |
| `vox voices` · `vox sample <ref> --play` | browse voices · hear a voice's sample |
| `vox say <text>` | synthesize (`-` reads stdin; `-o file.mp3`; `--play`) |
| `vox batch script.json` | multi-voice script → audio files, redoing only lines that changed |
| `vox transcribe <files>` | speech-to-text (`-m`, `-l zh`, `--hotwords`, `--diarize`, `--words`, `-f txt\|srt\|vtt\|json`, `-o`) |
| `vox transcripts [show\|rm]` | transcription records, shared with the web UI |
| `vox history [--star]` | history, shared with the web UI |
| `vox keys` · `vox providers` | credentials · providers, including custom ones |
| `vox serve` · `vox status` | web UI + API · server status and file locations |

When the server is running, `say`, `sample`, `load` and `unload` go through it and reuse models already in memory; `--local` forces in-process synthesis.

## Where things live

| | Location | Contents |
| --- | --- | --- |
| Data | `~/.vox` | synthesized clips, transcripts, samples, history, saved voices, settings, my models, custom providers |
| Models | `~/.vox/models` | local model files (excluded from Time Machine; they can be downloaded again) |
| Cache | `~/Library/Caches/vox` (`~/.cache/vox` elsewhere) | live model lists, cloud voice lists, registry updates — safe to delete |
| Keys | `~/.config/vox/credentials.json` | mode 600; environment variables take precedence |

`VOX_HOME` moves everything (handy for a portable setup or tests); `VOX_MODELS`, `VOX_CACHE` and `VOX_CONFIG` move one part each. Kokoro's own files live in the HuggingFace cache.

## The registry

`vox/registry.json` is data, not code: which providers exist, how to connect to them, and hand-checked details (capabilities, prices, voices) for the models vox recommends. Adapters in `vox/providers/` know *how* to talk to a provider; the registry says *what* is there. `vox models update` fetches the latest registry from this repository, so model details can be corrected without a new release. It only takes effect when it's newer than the one you have, and it refuses a registry that needs an adapter your version doesn't have.

## Contributing

To add a provider: write a `CloudEngine` subclass in `vox/providers/` (OpenAI-compatible ones only need registry entries), register it in `vox/registry.json`, and add an offline test that replays the provider's documented request and response. Research notes and sources for every provider are in [`docs/cloud-providers-2026-09.md`](docs/cloud-providers-2026-09.md) (Chinese).

## Acknowledgements

[Qwen3-TTS](https://huggingface.co/Qwen) · [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh) · [mlx-audio](https://github.com/Blaizzy/mlx-audio) and the [mlx-community](https://huggingface.co/mlx-community) conversions · the [ModelScope](https://modelscope.cn) mirror · provider icons from [LobeHub Icons](https://github.com/lobehub/lobe-icons) (MIT).

## License

[MIT](LICENSE). Model weights are downloaded from their publishers and keep their own licenses (Qwen3-TTS and Kokoro are Apache-2.0).
