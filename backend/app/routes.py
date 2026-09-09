from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from .database import async_session
from .models import TelemetryLog
from .websocket_manager import ConnectionManager


router = APIRouter()
manager = ConnectionManager()

TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"


@router.get("/", response_class=HTMLResponse)
async def get_frontend():
    return TEMPLATE_PATH.read_text(encoding="utf-8")


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.get("/api/telemetry/recent")
async def get_recent_telemetry(limit: int = 10):
    limit = max(1, min(limit, 100))

    async with async_session() as session:
        result = await session.execute(
            select(TelemetryLog)
            .order_by(TelemetryLog.timestamp.desc())
            .limit(limit)
        )

        logs = result.scalars().all()

        return [
            {
                "id": log.id,
                "timestamp": log.timestamp,
                "station_id": log.station_id,
                "external_temp": log.external_temp,
                "total_power_kw": log.total_power_kw,
                "payload": log.payload,
            }
            for log in logs
        ]