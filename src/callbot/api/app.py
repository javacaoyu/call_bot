"""FastAPI 应用工厂。"""

from fastapi import FastAPI, WebSocket

from callbot.api.calls import router as calls_router
from callbot.api.provider_config import router as provider_config_router
from callbot.channel.webrtc import SessionManager, handle_signaling
from callbot.config import Settings
from callbot.data.models import init_db
from callbot.logging import setup_logging


def create_app() -> FastAPI:
    """创建 FastAPI 应用（WebRTC 信令 + 配置 API + 通话记录 API）。"""
    settings = Settings()
    setup_logging(settings.log_level)  # 应用日志（转写/打断等 INFO 可见）
    init_db(settings)  # 通话记录表（幂等）
    app = FastAPI(title="callbot")
    app.include_router(provider_config_router)
    app.include_router(calls_router)
    manager = SessionManager()

    @app.websocket("/ws/signal")
    async def ws_signal(websocket: WebSocket) -> None:
        await websocket.accept()
        await handle_signaling(websocket, manager)

    return app
