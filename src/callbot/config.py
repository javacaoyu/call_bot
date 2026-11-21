"""应用配置（pydantic-settings）。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置。

    读取优先级：环境变量（前缀 `CALLBOT_`）> `.env` 文件 > 默认值。
    后续 Web 后台的 provider_config 等配置扩展基于此模式。
    """

    model_config = SettingsConfigDict(
        env_prefix="CALLBOT_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "callbot"
    env: str = "dev"
    log_level: str = "INFO"
    # 默认指向 docker-compose 起的本地库（凭据见 .env.example）
    db_url: str = "postgresql://callbot:callbot@127.0.0.1:5432/callbot"
    models_dir: str = "models"
    # LLM Provider（OpenAI 兼容，本地 vLLM/Ollama 换 base_url/model 即可）
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    # 编排层后端：agentscope（默认）| simple（自建 fallback）
    orchestration_backend: str = "agentscope"
    # Provider 切换（WBS 4.1/4.3）：三环节 kind 配置。
    # asr_kind: funasr（本地）| volc | qwen；tts_kind: cosyvoice（本地）| volc | qwen | aliyun
    asr_kind: str = "funasr"
    tts_kind: str = "cosyvoice"
    # 云端 ASR 密钥：volc/qwen 共用 asr_api_key（两平台同 Key 模式）
    asr_api_key: str = ""
    asr_resource_id: str = "volc.seedasr.sauc.duration"
    # 云端 TTS 密钥：aliyun 用 appkey +（token 直配优先，否则 access_key_id/secret 签名）
    tts_appkey: str = ""
    tts_token: str = ""
    tts_access_key_id: str = ""
    tts_access_key_secret: str = ""
    tts_voice: str = "longxiaochun"
    # 火山 TTS 音色（豆包语音合成 2.0 默认音色；api_key 复用 asr_api_key——
    # 火山同一账号 X-Api-Key 跨服务通用）
    tts_volc_speaker: str = "zh_female_vv_uranus_bigtts"
    # 千问 TTS 音色（Qwen-Audio-TTS 系统音色；api_key 复用 asr_api_key，同 Key）
    tts_qwen_voice: str = "longanhuan_v3.1"
    # VAD（WBS 3.1/3.4）：Silero 模型路径与灵敏度参数（相对路径基于项目根）。
    # min_speech_ms 为起音观察窗 = 打断灵敏度核心旋钮（越小打断越快但越易误触发）；
    # min_silence_ms 为端点静音容忍。
    vad_model_path: str = "models/silero_vad.jit"
    vad_threshold: float = 0.5
    vad_min_speech_ms: int = 250
    vad_min_silence_ms: int = 400
    # 收尾宽限：flush 后等待云端 ASR 判停增量并入完整转写的时长（ms）
    utterance_settle_ms: int = 800
