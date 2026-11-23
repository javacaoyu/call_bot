"""FastAPI 应用工厂。"""

from fastapi import FastAPI, WebSocket

from callbot.api.calls import router as calls_router
from callbot.api.customers import router as customers_router
from callbot.api.flows import router as flows_router
from callbot.api.personas import router as personas_router
from callbot.api.provider_config import router as provider_config_router
from callbot.api.scenes import router as scenes_router
from callbot.api.tools import router as tools_router
from callbot.channel.webrtc import SessionManager, handle_signaling
from callbot.config import Settings
from callbot.data.models import init_db
from callbot.logging import setup_logging
from callbot.tools.loader import load_plugins


def create_app() -> FastAPI:
    """创建 FastAPI 应用（WebRTC 信令 + 配置/通话/人设/客户/场景/流程/工具 API）。"""
    settings = Settings()
    setup_logging(settings.log_level)  # 应用日志（转写/打断等 INFO 可见）
    init_db(settings)  # 建表 + 种子（幂等）
    load_plugins()  # 代码插件注册（6.3；改插件需重启生效）
    app = FastAPI(title="callbot")
    app.include_router(provider_config_router)
    app.include_router(calls_router)
    app.include_router(personas_router)
    app.include_router(customers_router)
    app.include_router(scenes_router)
    app.include_router(tools_router)
    app.include_router(flows_router)
    manager = SessionManager()

    @app.websocket("/ws/signal")
    async def ws_signal(websocket: WebSocket) -> None:
        await websocket.accept()
        await handle_signaling(websocket, manager)

    return app
