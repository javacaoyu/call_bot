"""FastAPI 应用工厂。"""

from fastapi import FastAPI, WebSocket

from callbot.channel.webrtc import SessionManager, handle_signaling


def create_app() -> FastAPI:
    """创建 FastAPI 应用（含 WebRTC 信令路由 /ws/signal）。"""
    app = FastAPI(title="callbot")
    manager = SessionManager()

    @app.websocket("/ws/signal")
    async def ws_signal(websocket: WebSocket) -> None:
        await websocket.accept()
        await handle_signaling(websocket, manager)

    return app
