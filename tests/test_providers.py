"""云端适配器离线测试：不联网、不需要 Key。

拦截每个适配器的 http()，按各家官方文档的请求 / 响应格式造数据，检查：
  1. 请求：URL、认证头、请求体字段名（文本、音色、指令、语速、种子）是否与官方文档一致
  2. 响应：裸字节 / base64 / hex / 临时 URL / 分块流 能否解析并最终落成可播放的 wav
运行：.venv/bin/python -m pytest tests -q   或   .venv/bin/python tests/test_providers.py
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = Path(tempfile.mkdtemp(prefix="vox-test-"))
os.environ["VOX_CONFIG"] = str(TMP / "cfg")          # 凭证写到临时目录，不碰真实配置
os.environ["VOX_HOME"] = str(TMP / "home")

from vox import audio, catalog, credentials, hub  # noqa: E402
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
    """Provider 与模型解耦：获取模型列表、添加、停用、删除。"""

    def _discover(self, mod, provider, *responses):
        fake = Fake(*responses)
        old, mod.http = mod.http, fake
        try:
            return hub.discover(provider), fake.calls
        finally:
            mod.http = old

    def test_openai_filters_tts_and_marks_added(self):
        rs, calls = self._discover(openai_compat, "openai", {"data": [{"id": "gpt-4o-mini-tts"}, {"id": "tts-1-hd"}, {"id": "gpt-5"}, {"id": "whisper-1"}]})
        self.assertEqual(calls[0]["url"], "https://api.openai.com/v1/models")
        self.assertEqual({r["remote"]: r["added"] for r in rs}, {"gpt-4o-mini-tts": True, "tts-1-hd": False})

    def test_siliconflow_audio_type_excludes_asr(self):
        rs, calls = self._discover(openai_compat, "siliconflow", {"data": [{"id": "FunAudioLLM/CosyVoice2-0.5B"}, {"id": "FunAudioLLM/SenseVoiceSmall"}, {"id": "fishaudio/fish-speech-1.5"}]})
        self.assertTrue(calls[0]["url"].endswith("/models?type=audio"))
        self.assertEqual([r["remote"] for r in rs], ["FunAudioLLM/CosyVoice2-0.5B", "fishaudio/fish-speech-1.5"])
        self.assertTrue(rs[0]["added"])

    def test_elevenlabs_and_gemini(self):
        rs, _ = self._discover(elevenlabs, "elevenlabs", [{"model_id": "eleven_v3", "name": "Eleven v3", "can_do_text_to_speech": True},
                                                          {"model_id": "scribe_v1", "name": "Scribe", "can_do_text_to_speech": False}])
        self.assertEqual([r["remote"] for r in rs], ["eleven_v3"])
        rs, calls = self._discover(gemini, "gemini", {"models": [{"name": "models/gemini-3.8-flash-tts", "displayName": "Gemini 3.8 Flash TTS"}], "nextPageToken": "p2"},
                                   {"models": [{"name": "models/gemini-3.1-flash-tts-preview"}, {"name": "models/gemini-3.8-pro"}]})
        self.assertEqual([r["remote"] for r in rs], ["gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview"])
        self.assertEqual(calls[0]["headers"]["x-goog-api-key"], "gm-test")
        self.assertIn("pageToken=p2", calls[1]["url"])

    def test_no_list_endpoint(self):
        with self.assertRaises(hub.VoxError) as e:
            hub.discover("minimax")
        self.assertIn("手动添加", str(e.exception))

    def test_add_synth_disable_remove(self):
        r = hub.add_model("gemini", "gemini-3.1-flash-tts-preview")
        self.assertEqual(r["model"], "gemini/gemini-3.1-flash-tts-preview")
        calls, _ = run(gemini, "gemini/gemini-3.1-flash-tts-preview", Fake({"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(WAV).decode()}}]}}]}),
                       input="你好", voice="Kore")
        self.assertIn("gemini-3.1-flash-tts-preview", calls[0]["url"])   # 借用 Gemini 的适配器，只换模型名
        hub.set_enabled(r["model"], False)
        self.assertFalse(next(m for m in hub.models("gemini") if m["id"] == r["model"])["enabled"])
        self.assertFalse(any(v["model"] == r["model"] for v in hub.voices(with_samples=False)))  # 停用后不进音色库
        hub.remove_model(r["model"])
        self.assertIsNone(catalog.find_model(r["model"]))
        with self.assertRaises(hub.VoxError):
            hub.remove_model("gemini/gemini-3.8-flash-tts")  # 内置模型只能停用


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
