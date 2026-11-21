"""FastAPI 应用工厂。"""

from fastapi import FastAPI, WebSocket

from callbot.api.provider_config import router as provider_config_router
from callbot.channel.webrtc import SessionManager, handle_signaling
from callbot.config import Settings
from callbot.logging import setup_logging


def create_app() -> FastAPI:
    """创建 FastAPI 应用（WebRTC 信令 /ws/signal + 配置 API /api/provider_config）。"""
    setup_logging(Settings().log_level)  # 应用日志（转写/打断等 INFO 可见）
    app = FastAPI(title="callbot")
    app.include_router(provider_config_router)
    manager = SessionManager()

    @app.websocket("/ws/signal")
    async def ws_signal(websocket: WebSocket) -> None:
        await websocket.accept()
        await handle_signaling(websocket, manager)

    return app
