"""云端模型目录。字段与本地模型一致，另有：
  adapter   适配器：openai_compat / elevenlabs / gemini / mimo / dashscope / volcengine / minimax
  remote    Provider 那边的模型 ID
  key_env   主凭证的环境变量
  price     官方价格：{"amount", "currency", "per", "unit"}；unit 为 char / byte（UTF-8 字节）/ cjk2（汉字按 2 字符）/ token（只展示，不估算）
所有字段取自各家官方文档（2026-09 核对），调研记录见 docs/cloud-providers-2026-09.md。
"""
from __future__ import annotations

GEN_NONE: list[str] = []


def _v(pairs, lang="", gender=""):
    """把 (id, 名字, 性别, 描述) 或 (id, 描述) 转成音色字典。"""
    out = []
    for p in pairs:
        if len(p) == 4:
            vid, name, g, desc = p
        else:
            vid, desc = p
            name, g = vid, gender
        out.append({"voice": vid, "name": name, "gender": g, "lang": lang, "description": desc})
    return out


OPENAI_VOICES = _v([(v, "官方推荐" if v in ("marin", "cedar") else "官方内置音色（针对英语优化）") for v in
                    ("marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse")], lang="多语言")

STEPFUN_VOICES = _v([
    ("zixinnansheng", "自信男声", "男", ""), ("wenrounansheng", "温柔男声", "男", ""), ("wenrougongzi", "温柔公子", "男", ""),
    ("yuanqinansheng", "元气男声", "男", ""), ("cixingnansheng", "磁性男声", "男", ""), ("zhengpaiqingnian", "正派青年", "男", ""),
    ("qingniandaxuesheng", "青年大学生", "男", ""), ("boyinnansheng", "播音男声", "男", ""), ("ruyananshi", "儒雅男士", "男", ""),
    ("shenchennanyin", "深沉男音", "男", ""), ("shuangkuainansheng", "爽快男声", "男", ""),
    ("elegantgentle-female", "气质温婉", "女", ""), ("livelybreezy-female", "活力轻快", "女", ""), ("jingdiannvsheng", "经典女声", "女", ""),
    ("wenroushunv", "温柔熟女", "女", ""), ("tianmeinvsheng", "甜美女声", "女", ""), ("qingchunshaonv", "清纯少女", "女", ""),
    ("yuanqishaonv", "元气少女", "女", ""), ("linjiajiejie", "邻家姐姐", "女", ""), ("qinqienvsheng", "亲切女声", "女", ""),
    ("wenrounvsheng", "温柔女声", "女", ""), ("jilingshaonv", "机灵少女", "女", ""), ("ruanmengnvsheng", "软萌女声", "女", ""),
    ("youyanvsheng", "优雅女声", "女", ""), ("lengyanyujie", "冷艳御姐", "女", ""), ("shuangkuaijiejie", "爽快姐姐", "女", ""),
    ("wenjingxuejie", "文静学姐", "女", ""), ("linjiameimei", "邻家妹妹", "女", ""), ("zhixingjiejie", "知性姐姐", "女", ""),
    ("ganliannvsheng", "干练女声", "女", ""), ("qinhenvsheng", "亲和女声", "女", ""), ("huolinvsheng", "活力女声", "女", ""),
    ("vibrant-youth", "Vibrant Youth", "男", "英文音色"), ("lively-girl", "Lively Girl", "女", "英文音色"),
    ("soft-spoken-gentleman", "Soft-spoken Gentleman", "男", "英文音色"), ("magnetic-voiced-male", "Magnetic-voiced Male", "男", "英文音色"),
], lang="中文")

SILICON_VOICES = _v([("alex", "Alex", "男", "沉稳男声"), ("benjamin", "Benjamin", "男", "低沉男声"), ("charles", "Charles", "男", "磁性男声"),
                     ("david", "David", "男", "欢快男声"), ("anna", "Anna", "女", "沉稳女声"), ("bella", "Bella", "女", "激情女声"),
                     ("claire", "Claire", "女", "温柔女声"), ("diana", "Diana", "女", "欢快女声")], lang="中文")

MIMO_VOICES = _v([("mimo_default", "默认", "", "国内集群为冰糖，其他集群为 Mia"), ("冰糖", "冰糖", "女", "中文女声"), ("茉莉", "茉莉", "女", "中文女声"),
                  ("苏打", "苏打", "男", "中文男声"), ("白桦", "白桦", "男", "中文男声"), ("Mia", "Mia", "女", "英文女声"),
                  ("Chloe", "Chloe", "女", "英文女声"), ("Milo", "Milo", "男", "英文男声"), ("Dean", "Dean", "男", "英文男声")])

GEMINI_VOICES = _v([(v, s) for v, s in (
    ("Zephyr", "Bright 明亮"), ("Puck", "Upbeat 轻快"), ("Charon", "Informative 信息感"), ("Kore", "Firm 坚定"), ("Fenrir", "Excitable 兴奋"),
    ("Leda", "Youthful 年轻"), ("Orus", "Firm 坚定"), ("Aoede", "Breezy 轻松"), ("Callirrhoe", "Easy-going 随和"), ("Autonoe", "Bright 明亮"),
    ("Enceladus", "Breathy 气声"), ("Iapetus", "Clear 清晰"), ("Umbriel", "Easy-going 随和"), ("Algieba", "Smooth 顺滑"), ("Despina", "Smooth 顺滑"),
    ("Erinome", "Clear 清晰"), ("Algenib", "Gravelly 沙哑"), ("Rasalgethi", "Informative 信息感"), ("Laomedeia", "Upbeat 轻快"), ("Achernar", "Soft 柔和"),
    ("Alnilam", "Firm 坚定"), ("Schedar", "Even 平稳"), ("Gacrux", "Mature 成熟"), ("Pulcherrima", "Forward 外放"), ("Achird", "Friendly 友好"),
    ("Zubenelgenubi", "Casual 随意"), ("Vindemiatrix", "Gentle 温和"), ("Sadachbia", "Lively 活泼"), ("Sadaltager", "Knowledgeable 博学"), ("Sulafat", "Warm 温暖"))], lang="多语言")


QWEN3_TTS_VOICES = _v([
    ("Cherry", "芊悦", "女", "阳光"), ("Serena", "苏瑶", "女", "温柔"), ("Ethan", "晨煦", "男", "阳光"), ("Chelsie", "千雪", "女", "二次元"),
    ("Momo", "茉兔", "女", "撒娇"), ("Vivian", "十三", "女", "小暴躁"), ("Moon", "月白", "男", "率性"), ("Maia", "四月", "女", "知性"),
    ("Kai", "凯", "男", "舒缓"), ("Nofish", "不吃鱼", "男", ""), ("Bella", "萌宝", "女", "萝莉"), ("Eldric Sage", "沧明子", "男", "老者"),
    ("Mia", "乖小妹", "女", ""), ("Mochi", "沙小弥", "男", "童声"), ("Bellona", "燕铮莺", "女", "说书"), ("Vincent", "田叔", "男", "烟嗓"),
    ("Bunny", "萌小姬", "女", ""), ("Neil", "阿闻", "男", "新闻"), ("Elias", "墨讲师", "女", ""), ("Arthur", "徐大爷", "男", ""),
    ("Nini", "邻家妹妹", "女", ""), ("Seren", "小婉", "女", "助眠"), ("Pip", "顽屁小孩", "男", ""), ("Stella", "少女阿月", "女", ""),
], lang="中文")
QWEN3_TTS_DIALECT = [{"voice": v, "name": n, "gender": g, "lang": l, "description": f"{l}"} for v, n, g, l in (
    ("Jada", "Jada", "女", "上海话"), ("Dylan", "Dylan", "男", "北京话"), ("Li", "Li", "男", "南京话"), ("Marcus", "Marcus", "男", "陕西话"),
    ("Roy", "Roy", "男", "闽南语"), ("Peter", "Peter", "男", "天津话"), ("Sunny", "Sunny", "女", "四川话"), ("Eric", "Eric", "男", "四川话"),
    ("Rocky", "Rocky", "男", "粤语"), ("Kiki", "Kiki", "女", "粤语"))]

VOLC_FEMALE = "sophie 魅力苏菲|qingxinnvsheng 清新女声|cancan 知性灿灿|sajiaoxuemei 撒娇学妹|tianmeixiaoyuan 甜美小源|tianmeitaozi 甜美桃子|shuangkuaisisi 爽快思思|linjianvhai 邻家女孩|kefunvsheng 暖阳女声|xiaoxue 儿童绘本|jitangnv 鸡汤女|meilinvyou 魅力女友|liuchangnv 流畅女声|wenroumama 温柔妈妈|tvbnv TVB女声|qiaopinv 俏皮女声|zhishuaiyingzi 直率英子|gaolengyujie 高冷御姐|wenroushunv 温柔淑女|gufengshaoyu 古风少御|mengyatou 萌丫头|tiexinnvsheng 贴心女声|kailangjiejie 开朗姐姐|linxiao 林潇|lingling 玲玲姐姐|qinqienv 亲切女声|wenjingmaomao 文静毛毛|zhixingnv 知性女声|qingchezizi 清澈梓梓|tianmeiyueyue 甜美悦悦|roumeinvyou 柔美女友|wenrouxiaoya 温柔小雅|shaoergushi 少儿故事"
VOLC_MALE = "liufei 刘飞|shaonianzixin 少年梓辛|dayi 大壹|ruyayichen 儒雅逸辰|jieshuoxiaoming 解说小明|yizhipiannan 译制片男|linjiananhai 邻家男孩|ruyaqingnian 儒雅青年|qingcang 擎苍|wennuanahu 温暖阿虎|aojiaobazong 傲娇霸总|lanyinmianbao 懒音绵宝|fanjuanqingnian 反卷青年|huolixiaoge 活力小哥|baqiqingshu 霸气青叔|xuanyijieshuo 悬疑解说|cixingjieshuonan 磁性解说男声|gaolengchenwen 高冷沉稳|shenyeboke 深夜播客|kailangdidi 开朗弟弟|kailangxuezhang 开朗学长|youyoujunzi 悠悠君子|qingshuangnanda 清爽男大|yuanboxiaoshu 渊博小叔|yangguangqingnian 阳光青年|wenrouxiaoge 温柔小哥|guanggaojieshuo 广告解说"
VOLC_VOICES = ([{"voice": "zh_female_vv_uranus_bigtts", "name": "Vivi 2.0", "gender": "女", "lang": "中文", "description": "支持 8 种方言"},
                {"voice": "zh_female_xiaohe_uranus_bigtts", "name": "小何", "gender": "女", "lang": "中文", "description": "支持 8 种方言"},
                {"voice": "zh_male_m191_uranus_bigtts", "name": "云舟", "gender": "男", "lang": "中文", "description": "支持 8 种方言"},
                {"voice": "zh_male_taocheng_uranus_bigtts", "name": "小天", "gender": "男", "lang": "中文", "description": "支持 8 种方言"}]
               + [{"voice": f"zh_female_{x.split()[0]}_uranus_bigtts", "name": x.split()[1], "gender": "女", "lang": "中文", "description": ""} for x in VOLC_FEMALE.split("|")]
               + [{"voice": f"zh_male_{x.split()[0]}_uranus_bigtts", "name": x.split()[1], "gender": "男", "lang": "中文", "description": ""} for x in VOLC_MALE.split("|")])

MINIMAX_VOICES = _v([
    ("male-qn-qingse", "青涩青年", "男", ""), ("male-qn-jingying", "精英青年", "男", ""), ("male-qn-badao", "霸道青年", "男", ""),
    ("male-qn-daxuesheng", "青年大学生", "男", ""), ("female-shaonv", "少女", "女", ""), ("female-yujie", "御姐", "女", ""),
    ("female-chengshu", "成熟女性", "女", ""), ("female-tianmei", "甜美女性", "女", ""),
    ("Chinese (Mandarin)_Reliable_Executive", "沉稳高管", "男", ""), ("Chinese (Mandarin)_News_Anchor", "新闻女声", "女", ""),
    ("Chinese (Mandarin)_Gentleman", "温润男声", "男", ""), ("Chinese (Mandarin)_Warm_Bestie", "温暖闺蜜", "女", ""),
    ("Chinese (Mandarin)_Male_Announcer", "播报男声", "男", ""), ("Chinese (Mandarin)_Sweet_Lady", "甜美女声", "女", ""),
    ("Chinese (Mandarin)_Radio_Host", "电台男主播", "男", ""), ("Chinese (Mandarin)_Lyrical_Voice", "抒情男声", "男", ""),
    ("Chinese (Mandarin)_Gentle_Senior", "温柔学姐", "女", ""), ("Chinese (Mandarin)_Crisp_Girl", "清脆少女", "女", ""),
    ("Chinese (Mandarin)_Humorous_Elder", "搞笑大爷", "男", ""), ("Chinese (Mandarin)_Wise_Women", "阅历姐姐", "女", ""),
], lang="中文")

MINIMAX_EMOTIONS = ["开心", "伤心", "生气", "害怕", "厌恶", "惊讶", "平静"]


def _m(**kw):
    kw.setdefault("languages", ["多语言"])
    kw.setdefault("license", "商用 API")
    kw["caps"] = {"voices": True, "instructions": False, "design": False, "seed": False, "native_speed": True, **kw.get("caps", {})}
    return kw


CLOUD_MODELS = [
    # ---------- OpenAI 兼容 ----------
    _m(id="openai/gpt-4o-mini-tts", alias="gpt-4o-mini-tts", provider="openai", adapter="openai_compat", remote="gpt-4o-mini-tts", key_env="OPENAI_API_KEY",
       name="gpt-4o-mini-tts", family="OpenAI TTS", caps={"instructions": True}, params=["voice", "instructions", "speed"], default_voice="marin",
       compat={"list_models": {"match": "tts"}, "base": "https://api.openai.com/v1", "base_env": "OPENAI_BASE_URL", "instructions": "instructions", "speed": (0.25, 4)},
       voices=OPENAI_VOICES, price={"text": "文本 $0.60 + 音频 $12 / 百万 token", "unit": "token"},
       about="OpenAI 的指令式 TTS：instructions 用自然语言控制语气。13 个内置音色，针对英语优化。"),
    _m(id="inworld/inworld-tts-2", alias="inworld-tts-2", provider="inworld", adapter="openai_compat", remote="inworld-tts-2", key_env="INWORLD_API_KEY",
       name="Inworld TTS-2", family="Inworld", caps={"instructions": True, "design": False}, params=["voice", "instructions", "speed"], default_voice="Ashley",
       compat={"base": "https://api.inworld.ai/v1", "instructions": "instructions", "english_only": True, "speed": (0.5, 1.5),
               "list_voices": {"url": 'https://api.inworld.ai/voices/v1/voices?pageSize=200&filter=source="SYSTEM"', "kind": "inworld"}},
       voices=_v([("Ashley", "官方示例音色"), ("Dennis", "官方示例音色")], lang="多语言"), price={"amount": 25, "currency": "USD", "per": 1_000_000, "unit": "char"},
       about="OpenAI 兼容；instructions 控制语气（必须英文），支持 200+ 语言，普通话在最高档。配好 Key 后自动拉取完整音色库。"),
    _m(id="inworld/inworld-tts-2-flash", alias="inworld-tts-2-flash", provider="inworld", adapter="openai_compat", remote="inworld-tts-2-flash", key_env="INWORLD_API_KEY",
       name="Inworld TTS-2 Flash", family="Inworld", params=["voice", "speed"], default_voice="Ashley",
       compat={"base": "https://api.inworld.ai/v1", "speed": (0.5, 1.5), "list_voices": {"url": 'https://api.inworld.ai/voices/v1/voices?pageSize=200&filter=source="SYSTEM"', "kind": "inworld"}},
       voices=_v([("Ashley", "官方示例音色"), ("Dennis", "官方示例音色")], lang="多语言"), price={"amount": 15, "currency": "USD", "per": 1_000_000, "unit": "char"},
       about="低延迟版本（首字约 20ms），不支持语气指令，但文本里的 [laugh] 等非语言标签可用。"),
    _m(id="stepfun/stepaudio-3-tts", alias="stepaudio-3-tts", provider="stepfun", adapter="openai_compat", remote="stepaudio-3-tts", key_env="STEPFUN_API_KEY",
       name="StepAudio 3 TTS", family="阶跃星辰", languages=["中文", "英语"], caps={"instructions": True}, params=["voice", "instructions", "speed"], default_voice="wenrounvsheng",
       compat={"list_models": {"match": "tts"}, "base": "https://api.stepfun.com/v1", "base_env": "STEPFUN_BASE_URL", "instructions": "instruction", "speed": (0.5, 2),
               "list_voices": {"url": "https://api.stepfun.com/v1/audio/system_voices?model=step-tts-2", "kind": "stepfun"}},
       voices=STEPFUN_VOICES, price={"amount": 2.5, "currency": "CNY", "per": 10000, "unit": "char"},
       about="2026-09-15 发布。instruction 用自然语言控制语气（≤500 字），文本里的（括号）会被当作指令而不朗读。"),
    _m(id="stepfun/stepaudio-2.5-tts", alias="stepaudio-2.5-tts", provider="stepfun", adapter="openai_compat", remote="stepaudio-2.5-tts", key_env="STEPFUN_API_KEY",
       name="StepAudio 2.5 TTS", family="阶跃星辰", languages=["中文", "英语"], caps={"instructions": True}, params=["voice", "instructions", "speed"], default_voice="wenrounvsheng",
       compat={"list_models": {"match": "tts"}, "base": "https://api.stepfun.com/v1", "base_env": "STEPFUN_BASE_URL", "instructions": "instruction", "speed": (0.5, 2),
               "list_voices": {"url": "https://api.stepfun.com/v1/audio/system_voices?model=step-tts-2", "kind": "stepfun"}},
       voices=STEPFUN_VOICES, price={"amount": 5.8, "currency": "CNY", "per": 10000, "unit": "char"},
       about="上一代表现力模型，instruction ≤200 字。"),
    _m(id="siliconflow/cosyvoice2", alias="sf-cosyvoice2", provider="siliconflow", adapter="openai_compat", remote="FunAudioLLM/CosyVoice2-0.5B", key_env="SILICONFLOW_API_KEY",
       name="CosyVoice2（硅基流动）", family="硅基流动", languages=["中文", "英语"], caps={"instructions": True}, params=["voice", "instructions", "speed"], default_voice="claire",
       compat={"list_models": {"query": "?type=audio", "exclude": ("sensevoice", "whisper", "asr", "telespeech")}, "base": "https://api.siliconflow.cn/v1", "base_env": "SILICONFLOW_BASE_URL", "instructions": "prefix", "voice_prefix": True, "speed": (0.25, 4), "extra": {"sample_rate": 44100}},
       voices=SILICON_VOICES, price={"amount": 50, "currency": "CNY", "per": 1_000_000, "unit": "byte"},
       about="托管开源 CosyVoice2。指令写进正文（vox 自动拼成「指令<|endofprompt|>正文」），支持 [laughter] 等标签。"),
    # ---------- 专用适配器 ----------
    _m(id="elevenlabs/eleven_v3", alias="eleven_v3", provider="elevenlabs", adapter="elevenlabs", remote="eleven_v3", key_env="ELEVENLABS_API_KEY",
       name="Eleven v3", family="ElevenLabs", languages=["70+ 语言"], caps={"instructions": True, "seed": True, "native_speed": False},
       params=["voice", "instructions", "speed", "seed", "lang"], default_voice=None, voices=[],
       price={"amount": 0.10, "currency": "USD", "per": 1000, "unit": "char"},
       about="表现力最强的一档。instructions 会变成音频标签（如 [whispers]），支持 seed。配好 Key 后自动拉取官方音色。"),
    _m(id="elevenlabs/eleven_flash_v2_5", alias="eleven_flash_v2_5", provider="elevenlabs", adapter="elevenlabs", remote="eleven_flash_v2_5", key_env="ELEVENLABS_API_KEY",
       name="Eleven Flash v2.5", family="ElevenLabs", languages=["32 种语言"], caps={"seed": True}, params=["voice", "speed", "seed", "lang"], default_voice=None, voices=[],
       price={"amount": 0.05, "currency": "USD", "per": 1000, "unit": "char"}, about="低延迟（约 75ms），原生语速 0.7–1.2。"),
    _m(id="elevenlabs/eleven_multilingual_v2", alias="eleven_multilingual_v2", provider="elevenlabs", adapter="elevenlabs", remote="eleven_multilingual_v2", key_env="ELEVENLABS_API_KEY",
       name="Eleven Multilingual v2", family="ElevenLabs", languages=["29 种语言"], caps={"seed": True}, params=["voice", "speed", "seed", "lang"], default_voice=None, voices=[],
       price={"amount": 0.10, "currency": "USD", "per": 1000, "unit": "char"}, about="稳定的多语种模型，单次最长 1 万字符。"),
    _m(id="gemini/gemini-3.8-flash-tts", alias="gemini-3.8-flash-tts", provider="gemini", adapter="gemini", remote="gemini-3.8-flash-tts", key_env="GEMINI_API_KEY",
       name="Gemini 3.8 Flash TTS", family="Gemini", languages=["130 种语言"], caps={"instructions": True, "native_speed": False}, params=["voice", "instructions", "speed"],
       default_voice="Kore", voices=GEMINI_VOICES, price={"text": "音频 $9 / 百万 token（有免费层）", "unit": "token"},
       about="2026-09-22 发布。instructions 作为风格描述（speech_metadata.style），文本里可用 <laugh> 等标签。"),
    _m(id="gemini/gemini-3.8-flash-lite-tts", alias="gemini-3.8-flash-lite-tts", provider="gemini", adapter="gemini", remote="gemini-3.8-flash-lite-tts", key_env="GEMINI_API_KEY",
       name="Gemini 3.8 Flash Lite TTS", family="Gemini", languages=["101 种语言"], caps={"instructions": True, "native_speed": False}, params=["voice", "instructions", "speed"],
       default_voice="Kore", voices=GEMINI_VOICES, price={"text": "音频 $6 / 百万 token（有免费层）", "unit": "token"}, about="更便宜的一档，官方明确支持普通话和粤语。"),
    _m(id="mimo/mimo-v2.5-tts", alias="mimo-v2.5-tts", provider="mimo", adapter="mimo", remote="mimo-v2.5-tts", key_env="MIMO_API_KEY",
       name="MiMo V2.5 TTS", family="小米 MiMo", languages=["中文", "英语", "方言"], caps={"instructions": True, "native_speed": False}, params=["voice", "instructions", "speed"],
       default_voice="mimo_default", voices=MIMO_VOICES, price={"text": "限时免费", "unit": "token"},
       about="风格指令用自然语言写；文本里可用（开心）[叹气] 等标签，句首加（唱歌）还能唱。"),
    _m(id="mimo/mimo-v2.5-tts-voicedesign", alias="mimo-v2.5-tts-voicedesign", provider="mimo", adapter="mimo", remote="mimo-v2.5-tts-voicedesign", key_env="MIMO_API_KEY",
       name="MiMo V2.5 声音设计", family="小米 MiMo", languages=["中文", "英语"], caps={"voices": False, "instructions": True, "design": True, "native_speed": False},
       params=["instructions", "speed"], default_voice=None, voices=[], price={"text": "限时免费", "unit": "token"},
       about="没有预置音色：用一句话描述声音，模型现场设计。"),
    # ---------- 阿里云百炼 ----------
    _m(id="aliyun/qwen-audio-3.0-tts-plus", alias="qwen-audio-3.0-tts-plus", provider="aliyun", adapter="dashscope", dashscope_group="A", remote="qwen-audio-3.0-tts-plus",
       key_env="DASHSCOPE_API_KEY", name="Qwen-Audio 3.0 TTS Plus", family="阿里云百炼", languages=["中文", "多语言"],
       caps={"instructions": True, "seed": True}, params=["voice", "instructions", "speed", "seed"], default_voice="longanlingxin",
       voices=_v([("longanlingxin", "龙安灵心", "女", "知心"), ("longanlufeng", "龙安路风", "男", "开朗")], lang="中文"),
       price={"amount": 1.4, "currency": "CNY", "per": 10000, "unit": "char"},
       instr_examples=["温柔地安慰对方", "用播音腔字正腔圆地读", "带着笑意，语气轻快"],
       about="2026-07 发布。instruction 自然语言控制，文本里还能用 [whispers] [laughing] 等标签；支持 seed。另有 500+ 基础音色（ID 形如 qwen-audio-3.0-tts-plus-xxx）。"),
    _m(id="aliyun/cosyvoice-v3-flash", alias="cosyvoice-v3-flash", provider="aliyun", adapter="dashscope", dashscope_group="A", remote="cosyvoice-v3-flash",
       key_env="DASHSCOPE_API_KEY", name="CosyVoice v3 Flash", family="阿里云百炼", languages=["中文", "方言", "多语言"],
       caps={"instructions": True, "seed": True}, params=["voice", "instructions", "speed", "seed"], default_voice="longanhuan_v3",
       voices=_v([("longanhuan_v3", "龙安欢", "女", "欢脱元气，支持多方言与指令"), ("longhuhu_v3", "龙呼呼", "女", "女童，支持指令"),
                  ("longanyang", "龙安洋", "男", "阳光大男孩，支持指令"), ("longanhuan", "龙安欢", "女", "欢脱元气，支持指令")], lang="中文"),
       price={"amount": 0.8, "currency": "CNY", "per": 10000, "unit": "char"},
       instr_examples=["你说话的情感是happy。", "你说话的情感是sad。", "请用四川话表达。", "请用粤语表达。"],
       about="系统音色的指令只接受固定格式：「你说话的情感是<情感>。」或「请用<方言>表达。」（带句号）。"),
    _m(id="aliyun/qwen3-tts-instruct-flash", alias="qwen3-tts-instruct-flash", provider="aliyun", adapter="dashscope", dashscope_group="B", remote="qwen3-tts-instruct-flash",
       key_env="DASHSCOPE_API_KEY", name="Qwen3-TTS Instruct Flash（云端）", family="阿里云百炼", languages=["中文", "英语", "多语言"],
       caps={"instructions": True, "native_speed": False}, params=["voice", "instructions", "speed", "lang"], default_voice="Cherry",
       voices=QWEN3_TTS_VOICES, price={"amount": 0.8, "currency": "CNY", "per": 10000, "unit": "char"},
       instr_examples=["语速较快，语调上扬，适合介绍产品", "低沉缓慢，像深夜电台"],
       about="Qwen3-TTS 的云端指令版：instructions 自然语言控制语速和情绪（只对这 24 个音色有效），单次 ≤600 字。"),
    _m(id="aliyun/qwen3-tts-flash", alias="qwen3-tts-flash", provider="aliyun", adapter="dashscope", dashscope_group="B", remote="qwen3-tts-flash",
       key_env="DASHSCOPE_API_KEY", name="Qwen3-TTS Flash（云端）", family="阿里云百炼", languages=["中文", "方言", "多语言"],
       caps={"native_speed": False}, params=["voice", "speed", "lang"], default_voice="Cherry",
       voices=QWEN3_TTS_VOICES + QWEN3_TTS_DIALECT, price={"amount": 0.8, "currency": "CNY", "per": 10000, "unit": "char"},
       about="49 个音色，含上海话、北京话、四川话、粤语等方言；不支持指令。"),
    # ---------- 火山 豆包 ----------
    _m(id="volcengine/seed-tts-2.0", alias="seed-tts-2.0", provider="volcengine", adapter="volcengine", remote="seed-tts-2.0",
       key_env="VOLC_TTS_API_KEY", name="豆包语音合成 2.0", family="火山引擎 豆包", languages=["中文", "方言", "英语"],
       caps={"instructions": True}, params=["voice", "instructions", "speed"], default_voice="zh_female_vv_uranus_bigtts",
       voices=VOLC_VOICES, price={"amount": 3, "currency": "CNY", "per": 10000, "unit": "char"},
       instr_examples=["你可以用特别开心的语气说话吗？", "用很痛心的语气说", "像在哄小孩睡觉一样轻声说"],
       about="中文自然度第一梯队。instructions 作为「上文」（context_texts）引导语气，写成一句请求效果最好。"),
    # ---------- MiniMax ----------
    _m(id="minimax/speech-2.8-hd", alias="speech-2.8-hd", provider="minimax", adapter="minimax", remote="speech-2.8-hd",
       key_env="MINIMAX_API_KEY", name="Speech 2.8 HD", family="MiniMax", languages=["中文", "粤语", "40 种语言"],
       caps={"instructions": True}, params=["voice", "instructions", "speed"], default_voice="female-shaonv",
       voices=MINIMAX_VOICES, price={"amount": 3.5, "currency": "CNY", "per": 10000, "unit": "cjk2"},
       instr_examples=MINIMAX_EMOTIONS, instr_enum=True,
       about="情绪只能选枚举（开心 / 伤心 / 生气 / 害怕 / 厌恶 / 惊讶 / 平静）；文本里可写 (laughs)(sighs) 等语气词、<#0.5#> 停顿。配好 Key 后拉取 300+ 系统音色。"),
    _m(id="minimax/speech-2.8-turbo", alias="speech-2.8-turbo", provider="minimax", adapter="minimax", remote="speech-2.8-turbo",
       key_env="MINIMAX_API_KEY", name="Speech 2.8 Turbo", family="MiniMax", languages=["中文", "粤语", "40 种语言"],
       caps={"instructions": True}, params=["voice", "instructions", "speed"], default_voice="female-shaonv",
       voices=MINIMAX_VOICES, price={"amount": 2.0, "currency": "CNY", "per": 10000, "unit": "cjk2"},
       instr_examples=MINIMAX_EMOTIONS, instr_enum=True, about="更快更便宜的一档，能力同 HD。"),
]
