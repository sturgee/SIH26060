import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from datetime import datetime, timezone

from .database import async_session
from .models import TelemetryDocument, TelemetryValue
from .websocket_manager import ConnectionManager
from .time_series import query_range
from .time_utils import iso_utc


router = APIRouter()
manager = ConnectionManager()

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
                "timestamp": iso_utc(document.timestamp),
                "payload": document.payload,
            }
            for document in reversed(documents)
        ],
    }




@router.get("/api/telemetry/range")
async def get_telemetry_range(
    metric: str,
    start: str,
    end: str,
    station_id: str | None = None,
):
    """Return raw or proportionally aggregated telemetry for an exact time range."""
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid ISO timestamp. Use YYYY-MM-DDTHH:MM:SS") from exc

    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    if end_dt <= start_dt:
        raise HTTPException(status_code=400, detail="end must be later than start")

    return await query_range(metric, start_dt, end_dt, station_id)

@router.get("/api/telemetry/latest")
async def get_latest_telemetry():
    """Return the newest stored telemetry packet as a REST fallback for the UI."""
    async with async_session() as session:
        result = await session.execute(
            select(TelemetryDocument)
            .order_by(TelemetryDocument.timestamp.desc(), TelemetryDocument.id.desc())
            .limit(1)
        )
        document = result.scalar_one_or_none()

    if document is None:
        return {"timestamp": None, "station_id": None, "payload": None}

    return {
        "id": document.id,
        "timestamp": iso_utc(document.timestamp),
        "received_at": iso_utc(document.received_at),
        "station_id": document.station_id,
        "payload": document.payload,
    }


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    try:
        await websocket.send_json(await get_initial_telemetry())

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        await manager.disconnect(websocket)

    except Exception:
        await manager.disconnect(websocket)


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
                "timestamp": iso_utc(document.timestamp),
                "received_at": iso_utc(document.received_at),
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
            "timestamp": iso_utc(document.timestamp),
            "received_at": iso_utc(document.received_at),
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