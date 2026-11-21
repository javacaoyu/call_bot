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
    # Provider 切换（WBS 4.1/4.3）：三环节 kind 配置（云端 kind 在 4.2 接入）。
    # asr_kind: funasr（本地）| xfyun | volc；tts_kind: cosyvoice（本地）| aliyun
    asr_kind: str = "funasr"
    tts_kind: str = "cosyvoice"
    # 云端 ASR 密钥：xfyun 用 app_id/api_key/api_secret 三件套；volc 用 api_key + resource_id
    asr_app_id: str = ""
    asr_api_key: str = ""
    asr_api_secret: str = ""
    asr_resource_id: str = "volc.seedasr.sauc.duration"
    # 云端 TTS 密钥：aliyun 用 appkey +（token 直配优先，否则 access_key_id/secret 签名）
    tts_appkey: str = ""
    tts_token: str = ""
    tts_access_key_id: str = ""
    tts_access_key_secret: str = ""
    tts_voice: str = "longxiaochun"
    # VAD（WBS 3.1/3.4）：Silero 模型路径与灵敏度参数（相对路径基于项目根）。
    # min_speech_ms 为起音观察窗 = 打断灵敏度核心旋钮（越小打断越快但越易误触发）；
    # min_silence_ms 为端点静音容忍。
    vad_model_path: str = "models/silero_vad.jit"
    vad_threshold: float = 0.5
    vad_min_speech_ms: int = 250
    vad_min_silence_ms: int = 400
