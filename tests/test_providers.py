"""云端适配器离线测试：不联网、不需要 Key。

拦截每个适配器的 http()，按各家官方文档的请求 / 响应格式造数据，检查：
  1. 请求：URL、认证头、请求体字段名（文本、音色、指令、语速、种子）是否与官方文档一致
  2. 响应：裸字节 / base64 / hex / 临时 URL / 分块流 能否解析并最终落成可播放的 wav
  3. 模型清单：在线发现（各家列表接口、OpenRouter、HuggingFace）、我的模型的添加 / 移除、注册表更新
运行：.venv/bin/python -m pytest tests -q   或   .venv/bin/python tests/test_providers.py
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = Path(tempfile.mkdtemp(prefix="vox-test-"))
os.environ["VOX_CONFIG"] = str(TMP / "cfg")          # 凭证写到临时目录，不碰真实配置
os.environ["VOX_HOME"] = str(TMP / "home")
(TMP / "home" / "cache").mkdir(parents=True)
(TMP / "home" / "cache" / "kokoro-voices.json").write_text('["zf_001", "zm_010"]')   # Kokoro 音色清单平时联网取一次，测试里预置，保持离线

from vox import audio, catalog, credentials, discovery, fetch, hub  # noqa: E402
from vox.providers import base  # noqa: E402
from vox.providers import engine_for  # noqa: E402
from vox.providers import (dashscope, elevenlabs, gemini, mimo, minimax,  # noqa: E402
                           openai_compat, volcengine)


def _tone(fmt: str) -> bytes:
    """用 ffmpeg 生成 0.3 秒正弦波，作为假的 Provider 音频。"""
    out = TMP / f"tone.{fmt}"
    if not out.exists():
        extra = ["-f", "s16le", "-ac", "1", "-ar", "24000"] if fmt == "raw" else []
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3", *extra, str(out)], check=True)
    return out.read_bytes()


MP3, WAV, PCM = _tone("mp3"), _tone("wav"), _tone("raw")
KEYS = {"OPENAI_API_KEY": "sk-openai-test", "INWORLD_API_KEY": "aW53b3JsZDp0ZXN0", "STEPFUN_API_KEY": "step-test", "SILICONFLOW_API_KEY": "sf-test",
        "ELEVENLABS_API_KEY": "el-test", "GEMINI_API_KEY": "gm-test", "MIMO_API_KEY": "sk-mimo-test", "DASHSCOPE_API_KEY": "ds-test",
        "VOLC_TTS_API_KEY": "volc-test", "MINIMAX_API_KEY": "mm-test"}
for k, v in KEYS.items():
    credentials.set(k, v)


# 音色列表平时在后台联网更新；测试里一律关掉，保持离线（VoiceCacheTest 单独验证这套逻辑）
_REAL_PULL = base.CloudEngine._pull_voices
base.CloudEngine._pull_voices = lambda self, f, raise_errors=False: base._PULLING.discard(self.m["id"])


class patch_env:
    """临时改凭证（None 表示删除），退出时还原。"""

    def __init__(self, **kv):
        self.kv, self.old = kv, {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.old[k] = credentials.get(k)
            credentials.delete(k) if v is None else credentials.set(k, v)

    def __exit__(self, *a):
        for k, v in self.old.items():
            credentials.delete(k) if v is None else credentials.set(k, v)


class Fake:
    """替换适配器模块里的 http()，记录请求并按预设返回。"""

    def __init__(self, *responses):
        self.calls, self.responses = [], list(responses)

    def __call__(self, method, url, headers=None, body=None, timeout=120, raw=False):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "body": body})
        r = self.responses.pop(0)
        return 200, {}, r if isinstance(r, bytes) else json.dumps(r).encode()


def run(mod, model_id, fake, **req):
    m = catalog.find_model(model_id)
    old = mod.http
    mod.http = fake
    try:
        data, fmt = engine_for(m).synth(hub.normalize({"model": model_id, **req}))
    finally:
        mod.http = old
    out = TMP / f"{model_id.replace('/', '_')}.wav"
    dur = audio.bytes_to_wav(data, fmt, out, float(req.get("speed", 1)), engine_for(m).native_speed)
    return fake.calls, dur


class OpenAICompatTest(unittest.TestCase):
    def test_openai(self):
        calls, dur = run(openai_compat, "openai/gpt-4o-mini-tts", Fake(MP3), input="你好", voice="marin", instructions="开心", speed=1.2)
        c = calls[0]
        self.assertEqual(c["url"], "https://api.openai.com/v1/audio/speech")
        self.assertEqual(c["headers"]["Authorization"], "Bearer sk-openai-test")
        self.assertEqual({k: c["body"][k] for k in ("model", "input", "voice", "instructions", "speed", "response_format")},
                         {"model": "gpt-4o-mini-tts", "input": "你好", "voice": "marin", "instructions": "开心", "speed": 1.2, "response_format": "mp3"})
        self.assertGreater(dur, 0.2)

    def test_inworld_english_only_and_speed_clamp(self):
        calls, _ = run(openai_compat, "inworld/inworld-tts-2", Fake(MP3), input="你好", voice="Ashley", instructions="speak warmly", speed=3)
        self.assertEqual(calls[0]["url"], "https://api.inworld.ai/v1/audio/speech")
        self.assertEqual(calls[0]["body"]["speed"], 1.5)  # 官方上限 1.5
        self.assertEqual(calls[0]["body"]["instructions"], "speak warmly")
        with self.assertRaises(Exception) as e:
            run(openai_compat, "inworld/inworld-tts-2", Fake(MP3), input="你好", instructions="温柔地说")
        self.assertIn("英文", str(e.exception))

    def test_stepfun_singular_instruction(self):
        calls, _ = run(openai_compat, "stepfun/stepaudio-3-tts", Fake(MP3), input="你好", voice="wenrounvsheng", instructions="语速快")
        b = calls[0]["body"]
        self.assertEqual(calls[0]["url"], "https://api.stepfun.com/v1/audio/speech")
        self.assertEqual(b["instruction"], "语速快")
        self.assertNotIn("instructions", b)

    def test_siliconflow_prefix_and_voice(self):
        calls, _ = run(openai_compat, "siliconflow/cosyvoice2", Fake(MP3), input="今天真开心", voice="alex", instructions="用高兴的情感说")
        b = calls[0]["body"]
        self.assertEqual(b["model"], "FunAudioLLM/CosyVoice2-0.5B")
        self.assertEqual(b["voice"], "FunAudioLLM/CosyVoice2-0.5B:alex")
        self.assertEqual(b["input"], "用高兴的情感说<|endofprompt|>今天真开心")

    def test_inworld_voice_list(self):
        m = catalog.find_model("inworld/inworld-tts-2")
        fake = Fake({"voices": [{"voiceId": "Ashley", "displayName": "Ashley", "langCode": "en"}]})
        old, openai_compat.http = openai_compat.http, fake
        try:
            vs = engine_for(m).fetch_voices()
        finally:
            openai_compat.http = old
        self.assertIn('filter=source="SYSTEM"', fake.calls[0]["url"])
        self.assertEqual(vs[0]["voice"], "Ashley")


class DedicatedTest(unittest.TestCase):
    def test_elevenlabs_v3_tag_seed_and_speed(self):
        calls, dur = run(elevenlabs, "elevenlabs/eleven_v3", Fake(MP3), input="你好", voice="JBFqnCBsd6RMkjVDRZzb", instructions="whispers", seed=7, speed=1.1)
        c = calls[0]
        self.assertTrue(c["url"].startswith("https://api.elevenlabs.io/v1/text-to-speech/JBFqnCBsd6RMkjVDRZzb?output_format=mp3_44100_128"))
        self.assertEqual(c["headers"]["xi-api-key"], "el-test")
        self.assertEqual(c["body"]["text"], "[whispers] 你好")
        self.assertEqual(c["body"]["seed"], 7)
        self.assertNotIn("voice_settings", c["body"])  # v3 不收 speed，交给 ffmpeg
        self.assertGreater(dur, 0.2)

    def test_elevenlabs_flash_native_speed(self):
        calls, _ = run(elevenlabs, "elevenlabs/eleven_flash_v2_5", Fake(MP3), input="hi", voice="v1", speed=2)
        self.assertEqual(calls[0]["body"]["voice_settings"]["speed"], 1.2)

    def test_gemini_wav_and_pcm(self):
        resp = {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(WAV).decode()}}]}}]}
        calls, dur = run(gemini, "gemini/gemini-3.8-flash-tts", Fake(resp), input="你好", voice="Kore", instructions="cheerful")
        c = calls[0]
        self.assertEqual(c["url"], "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash-tts:generateContent")
        self.assertEqual(c["headers"]["x-goog-api-key"], "gm-test")
        self.assertEqual(c["body"]["contents"][0]["parts"][0]["speech_metadata"]["style"], "cheerful")
        self.assertEqual(c["body"]["generationConfig"]["speechConfig"]["voiceConfig"]["voice"], "Kore")
        self.assertGreater(dur, 0.2)
        resp_pcm = {"candidates": [{"content": {"parts": [{"inlineData": {"data": base64.b64encode(PCM).decode()}}]}}]}
        _, dur2 = run(gemini, "gemini/gemini-3.8-flash-lite-tts", Fake(resp_pcm), input="你好")
        self.assertAlmostEqual(dur2, 0.3, delta=0.05)  # 无头 L16 24k 单声道

    def test_mimo_roles(self):
        resp = {"choices": [{"message": {"audio": {"data": base64.b64encode(WAV).decode()}}}]}
        calls, _ = run(mimo, "mimo/mimo-v2.5-tts", Fake(resp), input="好消息！", voice="冰糖", instructions="开心")
        b = calls[0]["body"]
        self.assertEqual(calls[0]["url"], "https://api.xiaomimimo.com/v1/chat/completions")
        self.assertEqual(b["messages"], [{"role": "user", "content": "开心"}, {"role": "assistant", "content": "好消息！"}])
        self.assertEqual(b["audio"], {"format": "wav", "voice": "冰糖"})
        _, _ = run(mimo, "mimo/mimo-v2.5-tts-voicedesign", Fake(resp), input="你好", instructions="温柔女声")
        with self.assertRaises(Exception):
            hub.normalize({"model": "mimo/mimo-v2.5-tts-voicedesign", "input": "你好"})

    def test_dashscope_group_a_seed_url(self):
        resp = {"output": {"audio": {"url": "https://oss.example/x.mp3?sig=1"}}}
        calls, dur = run(dashscope, "aliyun/qwen-audio-3.0-tts-plus", Fake(resp, MP3), input="你好", voice="longanlingxin", instructions="温柔", seed=70000, speed=1.5)
        c = calls[0]
        self.assertEqual(c["url"], "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer")
        inp = c["body"]["input"]
        self.assertEqual((inp["text"], inp["voice"], inp["instruction"], inp["rate"], inp["seed"]), ("你好", "longanlingxin", "温柔", 1.5, 70000 % 65536))
        self.assertEqual(calls[1]["url"], "https://oss.example/x.mp3?sig=1")
        self.assertGreater(dur, 0.2)
        credentials.set("DASHSCOPE_WORKSPACE_ID", "llm-abc")
        calls, _ = run(dashscope, "aliyun/qwen-audio-3.0-tts-plus", Fake(resp, MP3), input="你好")
        self.assertEqual(calls[0]["url"], "https://llm-abc.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer")
        credentials.delete("DASHSCOPE_WORKSPACE_ID")

    def test_dashscope_group_b(self):
        resp = {"output": {"audio": {"url": "https://oss.example/y.wav"}}}
        calls, _ = run(dashscope, "aliyun/qwen3-tts-instruct-flash", Fake(resp, WAV), input="你好", voice="Cherry", instructions="语速较快")
        c = calls[0]
        self.assertTrue(c["url"].endswith("/multimodal-generation/generation"))
        self.assertEqual(c["body"]["input"], {"text": "你好", "voice": "Cherry", "language_type": "Chinese", "instructions": "语速较快"})

    def test_volcengine_chunks(self):
        half = len(MP3) // 2
        stream = "\n".join(json.dumps(x) for x in (
            {"code": 0, "message": "", "data": base64.b64encode(MP3[:half]).decode()},
            {"code": 0, "message": "", "data": None, "sentence": {"text": "你好"}},
            {"code": 0, "message": "", "data": base64.b64encode(MP3[half:]).decode()},
            {"code": 20000000, "message": "ok", "data": None, "usage": {"text_words": 2}})).encode()
        calls, dur = run(volcengine, "volcengine/seed-tts-2.0", Fake(stream), input="你好", instructions="你可以用开心的语气说吗？", speed=0.5)
        c = calls[0]
        self.assertEqual(c["url"], "https://openspeech.bytedance.com/api/v3/tts/unidirectional")
        self.assertEqual(c["headers"]["X-Api-Key"], "volc-test")
        self.assertEqual(c["headers"]["X-Api-Resource-Id"], "seed-tts-2.0")
        rp = c["body"]["req_params"]
        self.assertEqual(rp["audio_params"]["speech_rate"], -50)
        self.assertEqual(json.loads(rp["additions"]), {"context_texts": ["你可以用开心的语气说吗？"]})  # additions 必须是 JSON 字符串
        self.assertGreater(dur, 0.2)

    def test_volcengine_error(self):
        err = json.dumps({"code": 45000001, "message": "speaker not exist"}).encode()
        with self.assertRaises(Exception) as e:
            run(volcengine, "volcengine/seed-tts-2.0", Fake(err), input="你好")
        self.assertIn("45000001", str(e.exception))

    def test_minimax_hex_and_emotion(self):
        resp = {"data": {"audio": MP3.hex(), "status": 2}, "base_resp": {"status_code": 0, "status_msg": "success"}}
        calls, dur = run(minimax, "minimax/speech-2.8-hd", Fake(resp), input="你好", voice="female-shaonv", instructions="开心一点", speed=3)
        c = calls[0]
        self.assertEqual(c["url"], "https://api.minimax.cn/v1/t2a_v2")
        vs = c["body"]["voice_setting"]
        self.assertEqual((vs["voice_id"], vs["emotion"], vs["speed"]), ("female-shaonv", "happy", 2))
        self.assertEqual(c["body"]["output_format"], "hex")
        self.assertGreater(dur, 0.2)
        with self.assertRaises(Exception) as e:
            run(minimax, "minimax/speech-2.8-hd", Fake(resp), input="你好", instructions="像海盗一样")
        self.assertIn("枚举", str(e.exception))

    def test_minimax_business_error(self):
        resp = {"data": None, "base_resp": {"status_code": 2049, "status_msg": "invalid api key"}}
        with self.assertRaises(Exception) as e:
            run(minimax, "minimax/speech-2.8-hd", Fake(resp), input="你好")
        self.assertIn("2049", str(e.exception))


class ModelListTest(unittest.TestCase):
    """Provider 与模型解耦：在线发现、我的模型（添加 / 移除）、注册表更新。"""

    def _discover(self, provider, *responses):
        fake = Fake(*responses)
        old, discovery.http = discovery.http, fake
        try:
            return hub.discover(provider), fake.calls
        finally:
            discovery.http = old

    def tearDown(self):
        for f in (catalog.PREFS, *catalog.DISCOVERED.glob("*.json")) if catalog.DISCOVERED.exists() else (catalog.PREFS,):
            f.unlink(missing_ok=True)
        catalog.rebuild()

    def test_openai_filters_tts(self):
        r, calls = self._discover("openai", {"data": [{"id": "gpt-4o-mini-tts"}, {"id": "tts-1-hd"}, {"id": "gpt-5"}, {"id": "whisper-1"}]})
        self.assertEqual(calls[0]["url"], "https://api.openai.com/v1/models")
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer sk-openai-test")
        ms = {m["remote"]: m for m in r["models"] if m["task"] == "tts"}   # 这家的识别模型（注册表里登记的）另算
        self.assertEqual(set(ms), {"gpt-4o-mini-tts", "tts-1-hd"})
        self.assertEqual(ms["gpt-4o-mini-tts"]["source"], "registry")      # 注册表里有的保留核对过的信息
        self.assertTrue(ms["tts-1-hd"]["inferred"])                         # 注册表里没有的：能力按同家推断
        self.assertTrue(ms["gpt-4o-mini-tts"]["mine"])                      # 连接后默认带上推荐模型
        self.assertFalse(ms["tts-1-hd"]["mine"])                            # 新查到的要用户自己添加

    def test_siliconflow_audio_type_excludes_asr(self):
        r, calls = self._discover("siliconflow", {"data": [{"id": "FunAudioLLM/CosyVoice2-0.5B"}, {"id": "FunAudioLLM/SenseVoiceSmall"}, {"id": "fishaudio/fish-speech-1.5"}]})
        self.assertTrue(calls[0]["url"].endswith("/models?type=audio"))
        self.assertEqual(sorted(m["remote"] for m in r["models"] if m["task"] == "tts"), ["FunAudioLLM/CosyVoice2-0.5B", "fishaudio/fish-speech-1.5"])
        self.assertEqual([m["task"] for m in r["models"] if m["remote"] == "FunAudioLLM/SenseVoiceSmall"], ["stt"])   # 同一个 ID 只作识别模型出现

    def test_elevenlabs_and_gemini(self):
        r, _ = self._discover("elevenlabs", [{"model_id": "eleven_v3", "name": "Eleven v3", "can_do_text_to_speech": True},
                                             {"model_id": "eleven_v4", "name": "Eleven v4", "can_do_text_to_speech": True},
                                             {"model_id": "scribe_v1", "name": "Scribe", "can_do_text_to_speech": False}])
        self.assertIn("elevenlabs/eleven_v4", [m["id"] for m in r["models"]])
        self.assertNotIn("elevenlabs/scribe_v1", [m["id"] for m in r["models"]])
        r, calls = self._discover("gemini", {"models": [{"name": "models/gemini-3.8-flash-tts"}], "nextPageToken": "p2"},
                                  {"models": [{"name": "models/gemini-3.1-flash-tts-preview"}, {"name": "models/gemini-3.8-pro"}]})
        self.assertEqual(r["found"], 2)
        self.assertEqual(calls[0]["headers"]["x-goog-api-key"], "gm-test")
        self.assertIn("pageToken=p2", calls[1]["url"])

    def test_openrouter_public_list_voices_price(self):
        with patch_env(OPENROUTER_API_KEY=None):
            r, calls = self._discover("openrouter", {"data": [
                {"id": "fish-audio/s2.1-pro", "name": "Fish Audio: S2.1 Pro", "pricing": {"prompt": "0.000015", "completion": "0"}},
                {"id": "x-ai/grok-voice-tts-1.0", "name": "Grok Voice", "pricing": {"prompt": "0.000015", "completion": "0"}, "supported_voices": ["eve", "rex"]},
                {"id": "google/gemini-3.8-flash-tts", "pricing": {"prompt": "0.0000005", "completion": "0.000009"}, "supported_voices": ["Kore"]},
                {"id": "deepgram/flux-tts:free", "pricing": {"prompt": "0", "completion": "0"}, "supported_voices": ["flux-alexis-en"]}]})
        self.assertEqual(calls[0]["headers"], {})                           # 公开接口：不用 Key 也能浏览
        self.assertIn("output_modalities=speech", calls[0]["url"])
        ms = {m["remote"]: m for m in r["models"]}
        self.assertEqual(ms["fish-audio/s2.1-pro"]["price"], {"amount": 15.0, "currency": "USD", "per": 1000000, "unit": "char"})
        self.assertFalse(ms["fish-audio/s2.1-pro"]["caps"]["voices"])
        self.assertEqual(ms["x-ai/grok-voice-tts-1.0"]["voice_count"], 2)
        self.assertEqual(ms["deepgram/flux-tts:free"]["price"]["text"], "免费")
        self.assertIn("token", ms["google/gemini-3.8-flash-tts"]["price"]["text"])
        self.assertTrue(all(m["status"] == "needs_key" and not m["mine"] for m in ms.values()))

    def test_openrouter_synth(self):
        with patch_env(OPENROUTER_API_KEY="sk-or-test"):
            self._discover("openrouter", {"data": [{"id": "x-ai/grok-voice-tts-1.0", "pricing": {"prompt": "0.000015"}, "supported_voices": ["eve", "rex"]},
                                                   {"id": "fish-audio/s2.1-pro", "pricing": {"prompt": "0.000015"}}]})
            calls, dur = run(openai_compat, "openrouter/x-ai/grok-voice-tts-1.0", Fake(MP3), input="你好", voice="rex", speed=1.5, instructions="开心")
            c = calls[0]
            self.assertEqual(c["url"], "https://openrouter.ai/api/v1/audio/speech")
            self.assertEqual(c["headers"]["Authorization"], "Bearer sk-or-test")
            self.assertEqual({k: c["body"][k] for k in ("model", "voice", "input", "response_format")},
                             {"model": "x-ai/grok-voice-tts-1.0", "voice": "rex", "input": "你好", "response_format": "mp3"})
            self.assertNotIn("speed", c["body"])            # 各家对 speed 支持不一：交给 ffmpeg
            self.assertNotIn("instructions", c["body"])     # OpenRouter 的语音接口没有 instructions
            self.assertAlmostEqual(dur, 0.2, delta=0.05)     # 0.3 秒 × 1/1.5
            calls, _ = run(openai_compat, "openrouter/fish-audio/s2.1-pro", Fake(MP3), input="你好")
            self.assertNotIn("voice", calls[0]["body"])     # 没有预置音色的模型不传 voice
            ref = "openrouter/x-ai/grok-voice-tts-1.0:eve"   # 带斜杠的模型 ID 也能写音色引用
            self.assertEqual(hub.resolve_voice(ref), {"model": "openrouter/x-ai/grok-voice-tts-1.0", "voice": "eve"})

    def test_huggingface_local_variants(self):
        search = [{"id": "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-4bit", "downloads": 944},
                  {"id": "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit", "downloads": 5703},
                  {"id": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit", "downloads": 5156},
                  {"id": "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-4bit", "downloads": 2499}]
        tree = [{"type": "file", "path": "model.safetensors", "size": 1_500_000_000}, {"type": "file", "path": "config.json", "size": 2000}]
        r, calls = self._discover("local", search, tree, tree, tree)
        self.assertEqual(calls[0]["headers"], {})
        ids = [m["id"] for m in r["models"]]
        self.assertIn("local/qwen3-tts-0.6b-customvoice-4bit", ids)
        self.assertNotIn("local/qwen3-tts-1.7b-base-8bit", ids)                        # Base（克隆）没有对应引擎，不列
        self.assertEqual(sum(1 for m in r["models"] if m.get("repo", "").endswith("1.7B-CustomVoice-8bit")), 1)   # 与注册表的 qwen3 去重
        m = catalog.find_model("local/qwen3-tts-0.6b-customvoice-4bit")
        self.assertEqual((m["engine"], m["params_b"], m["quant"], m["size_gb"]), ("qwen3", 0.6, "MLX 4bit", 1.5))
        self.assertFalse(m["inferred"])
        self.assertEqual(catalog.find_model("local/qwen3-tts-1.7b-voicedesign-4bit")["engine"], "qwen3-design")

    def test_no_list_endpoint(self):
        with self.assertRaises(hub.VoxError) as e:
            hub.discover("minimax")
        self.assertIn("手动填模型 ID", str(e.exception))

    def test_mine_add_remove_custom(self):
        self.assertTrue(next(m for m in hub.models("minimax") if m["id"] == "minimax/speech-2.8-hd")["mine"])
        hub.remove_model("minimax/speech-2.8-hd")
        self.assertFalse(next(m for m in hub.models("minimax") if m["id"] == "minimax/speech-2.8-hd")["mine"])
        self.assertFalse(any(v["model"] == "minimax/speech-2.8-hd" for v in hub.voices(with_samples=False)))   # 不在我的模型，不进音色库
        hub.add_model("minimax/speech-2.8-hd")
        r = hub.add_model("minimax/speech-2.9-hd")                           # 列表接口查不到的，手动填模型 ID
        m = catalog.find_model(r["model"])
        self.assertEqual((m["source"], m["adapter"], m["remote"], m["name"]), ("custom", "minimax", "speech-2.9-hd", "speech-2.9-hd"))
        calls, _ = run(minimax, "minimax/speech-2.9-hd", Fake({"data": {"audio": MP3.hex()}, "base_resp": {"status_code": 0}}), input="你好")
        self.assertEqual(calls[0]["body"]["model"], "speech-2.9-hd")      # 借用同家的请求格式，只换模型名
        hub.remove_model("minimax/speech-2.9-hd")
        self.assertIsNone(catalog.find_model("minimax/speech-2.9-hd"))      # 手动添加的，移除后从目录消失

    def test_unconnected_provider(self):
        with patch_env(INWORLD_API_KEY=None):
            ms = hub.models("inworld")
            self.assertTrue(all(m["status"] == "needs_key" and not m["mine"] for m in ms))
            with self.assertRaises(hub.VoxError) as e:
                hub.add_model("inworld/inworld-tts-2")
            self.assertIn("先连接", str(e.exception))
            self.assertEqual(hub.models("inworld", mine=True), [])

    def test_local_remove_requires_confirmation(self):
        m = catalog.find_model("local/qwen3-design")
        d = fetch.local_dir(m["repo"])                                       # 测试目录里的假模型，不碰真实文件
        d.mkdir(parents=True, exist_ok=True)
        (d / "model.safetensors").write_bytes(b"x")
        (d / ".vox-complete").write_text("{}")
        self.assertTrue(next(x for x in hub.models("local") if x["id"] == m["id"])["mine"])
        with self.assertRaises(hub.VoxError) as e:
            hub.remove_model(m["id"])
        self.assertIn("--delete-files", str(e.exception))
        self.assertTrue(d.exists())
        hub.remove_model(m["id"], delete_files=True)
        self.assertFalse(d.exists())
        self.assertFalse(next(x for x in hub.models("local") if x["id"] == m["id"])["mine"])

    def test_registry_update(self):
        cur = json.loads(catalog.BUILTIN.read_text())
        fake = Fake({"schema": 2}, {**cur, "providers": {**cur["providers"], "newco": {"kind": "cloud", "adapter": "newco_adapter"}}}, cur,
                    {**cur, "updated": "2099-01-01", "models": cur["models"] + [{"provider": "openai", "remote": "gpt-9-tts", "name": "gpt-9-tts", "recommended": True}]})
        old, base.http = base.http, fake
        try:
            with self.assertRaises(hub.VoxError):
                hub.registry_update("https://example.invalid/r.json")       # 格式不对
            with self.assertRaises(hub.VoxError) as e:
                hub.registry_update("https://example.invalid/r.json")       # 需要新适配器 → 提示升级
            self.assertIn("升级", str(e.exception))
            self.assertFalse(hub.registry_update("https://example.invalid/r.json")["changed"])   # 同一版本
            r = hub.registry_update("https://example.invalid/r.json")
        finally:
            base.http = old
        self.assertTrue(r["changed"])
        self.assertEqual(catalog.find_model("openai/gpt-9-tts")["source"], "registry")
        catalog.UPDATED.unlink()
        catalog.rebuild()
        self.assertIsNone(catalog.find_model("openai/gpt-9-tts"))


class VoiceCacheTest(unittest.TestCase):
    """音色列表：先给手头有的，后台更新；失败 10 分钟内不重试；换 Key 清掉失败记录。"""

    def test_stale_while_revalidate(self):
        m = catalog.find_model("stepfun/stepaudio-3-tts")
        e = engine_for(m)
        f = base.CACHE / "stepfun__stepaudio-3-tts.json"
        f.unlink(missing_ok=True)
        f.with_suffix(".fail").unlink(missing_ok=True)
        calls = []
        e.fetch_voices = lambda: calls.append(1) or [{"voice": "online-1", "name": "在线音色"}]
        base.CloudEngine._pull_voices = _REAL_PULL
        try:
            first = e.voices()                                    # 立即返回静态音色，不等网络
            self.assertEqual(first[0]["voice"], m["voices"][0]["voice"])
            for _ in range(50):
                if f.exists():
                    break
                time.sleep(0.02)
            self.assertEqual(e.voices()[0]["voice"], "online-1")   # 后台拉到后，下次用在线列表
            self.assertEqual(len(calls), 1)
            f.unlink()

            def boom():
                raise base.ProviderError("HTTP 401：bad key")
            e.fetch_voices = boom
            e.voices()
            for _ in range(50):
                if f.with_suffix(".fail").exists():
                    break
                time.sleep(0.02)
            self.assertTrue(f.with_suffix(".fail").exists())      # 失败记一笔
            e.fetch_voices = lambda: calls.append(1) or []
            e.voices()
            time.sleep(0.1)
            self.assertEqual(len(calls), 1)                       # 10 分钟内不重试
            with self.assertRaises(base.ProviderError):
                e.fetch_voices = boom
                e.voices(refresh=True)                            # 显式刷新如实报错
            hub.set_key("STEPFUN_API_KEY", "step-test")
            self.assertFalse(f.with_suffix(".fail").exists())     # 换 Key 清掉失败记录
        finally:
            base.CloudEngine._pull_voices = lambda self, f, raise_errors=False: base._PULLING.discard(self.m["id"])
            del e.fetch_voices


class CustomProviderTest(unittest.TestCase):
    """自定义 Provider：OpenAI 兼容的自建服务 / 代理 / 新厂商，配置只存最少的字段。"""

    def tearDown(self):
        for pid in list(hub._custom_cfgs()):
            hub.provider_remove(pid)

    def test_keyless_local_server(self):
        fake = Fake({"data": [{"id": "kokoro"}, {"id": "whisper-1"}, {"id": "tts-1"}]})
        old, discovery.http = discovery.http, fake
        try:
            r = hub.provider_save("my-kokoro", {"name": "我的 Kokoro", "base_url": "http://127.0.0.1:8880/v1/", "auth": False, "instructions": "none", "native_speed": True})
        finally:
            discovery.http = old
        self.assertEqual((r["connected"], r["found"], r["key_env"]), (True, 3, None))
        self.assertEqual(fake.calls[0]["url"], "http://127.0.0.1:8880/v1/models")
        self.assertEqual(fake.calls[0]["headers"], {})                     # 不要 Key 的服务不发 Authorization
        p = catalog.PROVIDERS["my-kokoro"]
        self.assertEqual((p["custom"], p["letter"], p["base_url"]), (True, "我", "http://127.0.0.1:8880/v1"))
        hub.add_model("my-kokoro/kokoro")
        calls, _ = run(openai_compat, "my-kokoro/kokoro", Fake(MP3), input="你好", voice="af_bella", instructions="开心", speed=1.5)
        c = calls[0]
        self.assertEqual(c["url"], "http://127.0.0.1:8880/v1/audio/speech")
        self.assertNotIn("Authorization", c["headers"])
        self.assertEqual((c["body"]["model"], c["body"]["voice"], c["body"]["speed"]), ("kokoro", "af_bella", 1.5))
        self.assertNotIn("instructions", c["body"])                       # 声明了不支持，就不传
        m = next(x for x in hub.models("my-kokoro") if x["id"] == "my-kokoro/kokoro")
        self.assertTrue(m["mine"])
        self.assertFalse(m["inferred"])                                    # 能力是用户声明的，不标「推断」

    def test_key_filter_and_prefix_instructions(self):
        r = hub.provider_save("proxy", {"name": "Proxy", "base_url": "https://proxy.example/v1", "auth": True, "instructions": "prefix",
                                        "model_filter": "TTS", "native_speed": False, "voices": "alloy, nova", "fetch_voices": False})
        self.assertEqual((r["connected"], r["key_env"]), (False, "VOX_PROXY_API_KEY"))
        with self.assertRaises(hub.VoxError):
            hub.add_model("proxy/gpt-4o-mini-tts")                          # 没连接不能添加
        fake = Fake({"data": [{"id": "gpt-4o-mini-tts"}, {"id": "gpt-5"}]})
        old, discovery.http = discovery.http, fake
        try:
            r = hub.provider_save("proxy", {**hub._custom_cfgs()["proxy"]}, key="sk-proxy-1", overwrite=True)
        finally:
            discovery.http = old
        self.assertEqual((r["connected"], r["found"]), (True, 1))           # 按 tts 过滤
        self.assertEqual(fake.calls[0]["headers"]["Authorization"], "Bearer sk-proxy-1")
        hub.add_model("proxy/gpt-4o-mini-tts")
        m = catalog.find_model("proxy/gpt-4o-mini-tts")
        self.assertEqual([v["voice"] for v in m["voices"]], ["alloy", "nova"])
        calls, dur = run(openai_compat, "proxy/gpt-4o-mini-tts", Fake(MP3), input="你好", instructions="开心", speed=1.5)
        b = calls[0]["body"]
        self.assertEqual(b["input"], "开心<|endofprompt|>你好")
        self.assertNotIn("speed", b)                                       # 不支持原生语速：交给 ffmpeg
        self.assertAlmostEqual(dur, 0.2, delta=0.05)
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer sk-proxy-1")
        hub.provider_remove("proxy")
        self.assertNotIn("proxy", catalog.PROVIDERS)
        self.assertIsNone(credentials.get("VOX_PROXY_API_KEY"))             # 连同保存的 Key 一起删
        self.assertIsNone(catalog.find_model("proxy/gpt-4o-mini-tts"))

    def test_unreachable_server_is_a_clear_error(self):
        def drop(*a, **k):
            raise base.ProviderError("a.example 连接异常：RemoteDisconnected")
        old, discovery.http = discovery.http, drop
        try:
            r = hub.provider_save("flaky", {"base_url": "http://a.example/v1", "auth": False})
        finally:
            discovery.http = old
        self.assertIsNone(r["found"])
        self.assertIn("连接异常", r["error"])                               # 保存成功，模型列表失败给出原因

    def test_voice_list_formats(self):
        from vox.providers.openai_compat import parse_voice_list
        self.assertEqual([v["voice"] for v in parse_voice_list(["a", "b"])], ["a", "b"])
        self.assertEqual([v["voice"] for v in parse_voice_list({"voices": ["af_bella"]})], ["af_bella"])
        vs = parse_voice_list({"data": [{"voice_id": "v1", "name": "Nova", "gender": "female"}, {"id": "v2"}, {"foo": 1}]})
        self.assertEqual([(v["voice"], v["name"], v["gender"]) for v in vs], [("v1", "Nova", "女"), ("v2", "v2", "")])

    def test_validation(self):
        for pid, cfg, msg in (("x", {"base_url": "http://a/v1"}, "ID"), ("ok-id", {"base_url": "ftp://a"}, "http"),
                              ("openai", {"base_url": "http://a/v1"}, "内置"), ("ok-id", {"base_url": "http://a/v1", "instructions": "xml"}, "情绪")):
            with self.assertRaises(hub.VoxError) as e:
                hub.provider_save(pid, {"auth": False, **cfg})
            self.assertIn(msg, str(e.exception))
        old, discovery.http = discovery.http, Fake({"data": []})
        try:
            hub.provider_save("dup", {"base_url": "http://a/v1", "auth": False, "fetch_voices": False})
        finally:
            discovery.http = old
        with self.assertRaises(hub.VoxError):
            hub.provider_save("dup", {"base_url": "http://b/v1", "auth": False})
        with self.assertRaises(hub.VoxError):
            hub.provider_remove("openai")


class GatewayTest(unittest.TestCase):
    def test_missing_key_message(self):
        credentials.delete("OPENAI_API_KEY")
        try:
            with self.assertRaises(Exception) as e:
                hub.speak({"model": "openai/gpt-4o-mini-tts", "input": "hi"})
            self.assertIn("OPENAI_API_KEY", str(e.exception))
        finally:
            credentials.set("OPENAI_API_KEY", KEYS["OPENAI_API_KEY"])

    def test_credentials_never_leak(self):
        dump = json.dumps(hub.provider_list())
        for v in KEYS.values():
            self.assertNotIn(v, dump)
        self.assertEqual(oct(os.stat(credentials.PATH).st_mode)[-3:], "600")

    def test_voice_ref_with_colon(self):
        self.assertEqual(hub.resolve_voice("sf-cosyvoice2:FunAudioLLM/CosyVoice2-0.5B:alex")["voice"], "FunAudioLLM/CosyVoice2-0.5B:alex")

    def test_estimate(self):
        self.assertAlmostEqual(hub.estimate({"model": "minimax/speech-2.8-hd", "input": "你好ab"})["amount"], 3.5 * 6 / 10000)
        self.assertAlmostEqual(hub.estimate({"model": "siliconflow/cosyvoice2", "input": "你好"})["amount"], 50 * 6 / 1_000_000)


class GeminiVoiceListTest(unittest.TestCase):
    def test_paginates_and_keeps_standard_voices(self):
        m = catalog.find_model("gemini/gemini-3.8-flash-tts")
        fake = Fake({"voices": [{"id": "achernar", "gender": "female", "language_code": "multi"}, {"id": "en-us-host-1", "display_name": "Host 1", "language_code": "en-US"}], "next_page_token": "p/2"},
                    {"voices": [{"id": "zephyr"}, {"id": "cmn-cn-narrator-3", "display_name": "旁白 3", "gender": "male", "language_code": "cmn-CN"}]})
        old, gemini.http = gemini.http, fake
        try:
            vs = engine_for(m).fetch_voices()
        finally:
            gemini.http = old
        self.assertEqual(len(fake.calls), 2)
        self.assertIn("page_size=1000", fake.calls[0]["url"]); self.assertIn("page_token=p%2F2", fake.calls[1]["url"])
        ids = [v["voice"] for v in vs]
        std = [v["voice"] for v in engine_for(m).static_voices()]
        self.assertEqual(ids[:len(std)], std)                       # 标准音色在前、带注册表里的说明
        self.assertNotIn("achernar", ids); self.assertNotIn("zephyr", ids)   # 大小写不同的同名音色不重复
        self.assertIn("cmn-cn-narrator-3", ids)                      # 第二页（中文）也拿到了
        self.assertEqual(next(v for v in vs if v["voice"] == "cmn-cn-narrator-3")["gender"], "男")


class STTTest(unittest.TestCase):
    """语音识别：模型目录的任务隔离、请求检查、云端响应解析、本地流程、缓存与输出格式（全部离线）。"""

    @classmethod
    def setUpClass(cls):
        from vox import stt
        cls.stt = stt

    def test_catalog_separates_tasks(self):
        import json as _j
        reg = _j.loads(catalog.BUILTIN.read_text())
        self.assertTrue(all("task" not in e for e in reg["models"]))           # 旧版只认 models：里面不能混进识别模型
        stts = [m for m in catalog.MODELS if m["task"] == "stt"]
        self.assertTrue(stts and all(not m["voices"] and not m["caps"]["voices"] for m in stts))
        sf = catalog.find_model("siliconflow/FunAudioLLM/SenseVoiceSmall")
        self.assertEqual(sf["task"], "stt")
        self.assertNotIn("voice_prefix", sf["compat"]); self.assertNotIn("extra", sf["compat"])   # 合成专用配置不带进识别
        self.assertEqual(sf["compat"]["base"], "https://api.siliconflow.cn/v1")
        self.assertIn("stt", catalog.custom_provider("x", {"base_url": "http://h/v1", "auth": False}))

    def test_request_checks(self):
        with self.assertRaises(hub.VoxError):
            self.stt.normalize({"model": "local/qwen3"})                         # 合成模型不能识别
        with self.assertRaises(hub.VoxError):
            hub.normalize({"model": "local/qwen3-asr", "input": "x"})            # 识别模型不能合成
        with self.assertRaises(hub.VoxError) as e:
            self.stt.normalize({"model": "local/qwen3-asr", "diarize": True})
        self.assertIn("gpt-4o-transcribe-diarize", str(e.exception))             # 报错里给出能用的模型
        r = self.stt.normalize({"model": "local/whisper-turbo", "language": "ZH", "prompt": "vox", "hotwords": "a，b"})
        self.assertEqual(r, {"model": "local/whisper-turbo", "language": "zh", "prompt": "vox"})   # whisper 不认热词：不传
        self.assertEqual(self.stt.normalize({"model": "qwen3-asr", "hotwords": "a，b", "language": "auto"})["hotwords"], ["a", "b"])

    def _cloud(self, model_id, resp, **req):
        from vox.providers import openai_compat
        m = catalog.find_model(model_id)
        fake = Fake(resp)
        old = openai_compat.http
        openai_compat.http = fake
        try:
            wav = TMP / "speech.wav"; wav.write_bytes(WAV)
            rec = self.stt.transcribe(wav, {"model": m["id"], "cache": False, **req}, source="test")
        finally:
            openai_compat.http = old
        return rec, fake.calls[0]

    def test_openai_verbose_json_words(self):
        resp = {"text": "你好 世界", "language": "chinese", "duration": 0.3,
                "segments": [{"start": 0, "end": 0.15, "text": " 你好"}, {"start": 0.15, "end": 0.3, "text": "世界"}],
                "words": [{"word": "你好", "start": 0, "end": 0.1}]}
        rec, call = self._cloud("openai/whisper-1", resp, words=True, language="zh", prompt="vox")
        self.assertEqual(call["url"], "https://api.openai.com/v1/audio/transcriptions")
        self.assertTrue(call["headers"]["Content-Type"].startswith("multipart/form-data; boundary="))
        body = call["body"]
        for field in (b'name="model"\r\n\r\nwhisper-1', b'name="response_format"\r\n\r\nverbose_json', b'name="language"\r\n\r\nzh',
                      b'name="prompt"\r\n\r\nvox', b'name="timestamp_granularities[]"\r\n\r\nword', b'filename="speech.wav"'):
            self.assertIn(field, body)
        self.assertEqual(rec["segments"][0], {"start": 0.0, "end": 0.15, "text": "你好"})
        self.assertEqual(rec["words"][0]["word"], "你好")
        self.assertIsNotNone(rec["cost"])
        self.assertIn("00:00:00,150 --> 00:00:00,300\n世界", self.stt.render(rec, "srt"))
        self.assertTrue(self.stt.render(rec, "vtt").startswith("WEBVTT\n\n00:00:00.000 --> 00:00:00.150\n你好"))   # vtt 不带序号

    def test_openai_diarized(self):
        resp = {"text": "a b", "duration": 0.3, "segments": [{"speaker": "A", "start": 0, "end": 0.1, "text": "a"}, {"speaker": "B", "start": 0.1, "end": 0.3, "text": "b"}]}
        rec, call = self._cloud("openai/gpt-4o-transcribe-diarize", resp, diarize=True)
        self.assertIn(b'name="chunking_strategy"\r\n\r\nauto', call["body"])
        self.assertEqual(self.stt.render(rec, "txt"), "[A] a\n[B] b\n")
        self.assertIn("[B] b", self.stt.render(rec, "srt"))

    def test_local_flow_cache_and_untimed_subtitles(self):
        calls = []

        class FakeASR:
            def transcribe(self, wav, language=None, prompt=None, hotwords=None):
                calls.append((wav, language, hotwords))
                return {"text": "测试一下", "language": "zh", "segments": [{"start": 0, "end": 0.3, "text": "测试一下"}]}

        old = hub._engine
        hub._engine = lambda m: FakeASR()
        try:
            src = TMP / "clip.mp3"; src.write_bytes(MP3)
            r1 = self.stt.transcribe(src, {"model": "qwen3-asr", "hotwords": ["vox"]}, source="test")
            r2 = self.stt.transcribe(src, {"model": "qwen3-asr", "hotwords": ["vox"]}, source="test")
            r3 = self.stt.transcribe(src, {"model": "qwen3-asr", "hotwords": ["vox"], "cache": False}, source="test")
        finally:
            hub._engine = old
        self.assertEqual(len(calls), 2)                                          # 第二次命中缓存
        self.assertTrue(calls[0][0].endswith("in.wav")); self.assertEqual(calls[0][2], ["vox"])
        self.assertTrue(r2.get("cached")); self.assertEqual(r1["id"], r3["id"])
        self.assertGreater(r1["duration"], 0.2)                                  # 时长来自转换后的 wav
        self.assertEqual(self.stt.get(r1["id"])["text"], "测试一下")
        self.assertIn(r1["id"], [x["id"] for x in self.stt.records()])
        self.assertEqual(self.stt.render(r1, "txt"), "测试一下\n")
        with self.assertRaises(hub.VoxError) as e:
            self.stt.render(r1, "srt")                                            # Qwen3-ASR 只有分块、没有分句：不假装能出字幕
        self.assertIn("whisper-turbo", str(e.exception))
        self.stt.delete(r1["id"])
        with self.assertRaises(hub.VoxError):
            self.stt.get(r1["id"])

    def test_upload_transcode(self):
        src = TMP / "u.wav"; src.write_bytes(WAV)
        self.assertEqual(audio.for_upload(src, ["wav", "mp3"], 25, TMP), src)                  # 支持的格式、没超限：原样
        up = audio.for_upload(src, ["mp3"], 25, TMP)
        self.assertEqual(up.suffix, ".mp3"); self.assertTrue(up.exists())
        with self.assertRaises(ValueError):
            audio.for_upload(src, ["mp3"], 0.000001, TMP)                                     # 压缩后还超限：报错而不是硬传

    def test_estimate_by_duration(self):
        m = catalog.find_model("openai/gpt-transcribe")
        self.assertAlmostEqual(self.stt.estimate(m, 600)["amount"], 0.27 / 6, places=4)       # 10 分钟 = 0.045 美元


class CacheTest(unittest.TestCase):
    """同样的请求命中缓存；cache=False 重新合成。不支持种子的模型得到新的一条，旧的保留。"""

    def setUp(self):
        self.calls, self._old = [], hub._render
        def render(req, out):
            self.calls.append(req); out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(WAV); return 0.3
        hub._render = render

    def tearDown(self):
        hub._render = self._old

    def test_seedless_regenerate(self):
        req = {"model": "openai/gpt-4o-mini-tts", "input": "缓存测试", "voice": "alloy"}
        a = hub.speak(dict(req)); b = hub.speak(dict(req))
        self.assertEqual(a["id"], b["id"]); self.assertTrue(b.get("cached")); self.assertEqual(len(self.calls), 1)
        c = hub.speak({**req, "cache": False})
        self.assertNotEqual(c["id"], a["id"]); self.assertFalse(c.get("cached")); self.assertEqual(len(self.calls), 2)
        ids = [h["id"] for h in hub.history()]
        self.assertIn(a["id"], ids); self.assertIn(c["id"], ids)
        self.assertNotIn("cache", c["request"])   # 记录下来的请求保持干净


class ServerDiscoveryTest(unittest.TestCase):
    """CLI 只找「用同一份数据」的服务：server.json 由服务写在自己的数据目录里。"""

    def setUp(self):
        from vox import cli, paths
        self.cli, self.paths = cli, paths
        self._url = os.environ.pop("VOX_URL", None)

    def tearDown(self):
        self.paths.SERVER_FILE.unlink(missing_ok=True)
        if self._url is not None:
            os.environ["VOX_URL"] = self._url

    def test_live_and_stale(self):
        self.paths.SERVER_FILE.write_text(json.dumps({"url": "http://127.0.0.1:9999", "pid": os.getpid()}))
        self.assertEqual(self.cli._find_server(), ("http://127.0.0.1:9999", False))
        dead = subprocess.Popen(["true"]); dead.wait()
        self.paths.SERVER_FILE.write_text(json.dumps({"url": "http://127.0.0.1:9999", "pid": dead.pid}))
        self.assertEqual(self.cli._find_server(), ("http://127.0.0.1:8765", False))
        self.assertFalse(self.paths.SERVER_FILE.exists())   # 没正常退出留下的记录被清掉

    def test_explicit_url_wins(self):
        os.environ["VOX_URL"] = "http://example:1/"
        try:
            self.assertEqual(self.cli._find_server(), ("http://example:1", True))
        finally:
            del os.environ["VOX_URL"]


if __name__ == "__main__":
    unittest.main(verbosity=2)
