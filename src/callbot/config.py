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
    # 默认指向 docker-compose 起的本地库（1.2 产物，凭据见 .env.example）
    db_url: str = "postgresql://voicebot:voicebot@127.0.0.1:5432/voicebot"
    models_dir: str = "models"
