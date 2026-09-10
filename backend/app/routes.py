import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from .database import async_session
from .models import TelemetryDocument, TelemetryValue
from .websocket_manager import ConnectionManager


router = APIRouter()
manager = ConnectionManager()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = PROJECT_ROOT / "frontend" / "templates" / "index.html"


@router.get("/", response_class=HTMLResponse)
async def get_frontend():
    return TEMPLATE_PATH.read_text(encoding="utf-8")


# ... Keep lines 1-25 unchanged ...

async def get_initial_telemetry() -> dict:
    async with async_session() as session:
        result = await session.execute(
            select(TelemetryDocument)
            .order_by(TelemetryDocument.timestamp.desc())
            .limit(20)  # ⚡ CHANGED: Reduced from 100 to 20 for lightning-fast loads
        )

        documents = result.scalars().all()

    return {
        "type": "initial",
        "latest": documents[0].payload if documents else None,
        "history": [
            {
                "timestamp": document.timestamp.isoformat(),
                "payload": document.payload,
            }
            for document in reversed(documents)
        ],
    }


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    try:
        await websocket.send_json(await get_initial_telemetry())

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        manager.disconnect(websocket)

    except Exception:
        manager.disconnect(websocket)


@router.get("/api/telemetry/recent")
async def get_recent_telemetry(limit: int = 10):
    limit = max(1, min(limit, 100))

    async with async_session() as session:
        result = await session.execute(
            select(TelemetryDocument)
            .order_by(TelemetryDocument.timestamp.desc())
            .limit(limit)
        )

        documents = result.scalars().all()

        return [
            {
                "id": document.id,
                "timestamp": document.timestamp,
                "received_at": document.received_at,
                "station_id": document.station_id,
                "payload": document.payload,
            }
            for document in documents
        ]


@router.get("/api/telemetry/{document_id}")
async def get_telemetry_document(document_id: int):
    async with async_session() as session:
        document_result = await session.execute(
            select(TelemetryDocument).where(
                TelemetryDocument.id == document_id
            )
        )
        document = document_result.scalar_one_or_none()

        if document is None:
            raise HTTPException(
                status_code=404,
                detail="Telemetry document not found",
            )

        values_result = await session.execute(
            select(TelemetryValue)
            .where(TelemetryValue.document_id == document_id)
            .order_by(TelemetryValue.path)
        )

        values = values_result.scalars().all()

        return {
            "id": document.id,
            "station_id": document.station_id,
            "timestamp": document.timestamp,
            "received_at": document.received_at,
            "payload": document.payload,
            "values": [
                {
                    "path": value.path,
                    "type": value.value_type,
                    "text": value.value_text,
                    "number": value.value_number,
                    "boolean": value.value_boolean,
                    "json": value.value_json,
                }
                for value in values
            ],
        }