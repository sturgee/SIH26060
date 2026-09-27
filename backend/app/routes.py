import asyncio
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types
from pydantic import BaseModel
from sqlalchemy import select

from .database import async_session
from .models import TelemetryDocument, TelemetryMeasurement, TelemetryValue
from .time_series import query_range
from .time_utils import iso_utc
from .websocket_manager import ConnectionManager

router = APIRouter()
manager = ConnectionManager()


async def get_initial_telemetry() -> dict:
    async with async_session() as session:
        result = await session.execute(
            select(TelemetryDocument)
            .order_by(TelemetryDocument.timestamp.desc())
            .limit(20)  # Reduced for fast initial load
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
        raise HTTPException(
            status_code=400,
            detail="Invalid ISO timestamp. Use YYYY-MM-DDTHH:MM:SS",
        ) from exc

    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    if end_dt <= start_dt:
        raise HTTPException(
            status_code=400, detail="end must be later than start"
        )

    return await query_range(metric, start_dt, end_dt, station_id)


@router.get("/api/telemetry/latest")
async def get_latest_telemetry():
    """Return the newest stored telemetry packet as a REST fallback for the UI."""
    async with async_session() as session:
        result = await session.execute(
            select(TelemetryDocument)
            .order_by(
                TelemetryDocument.timestamp.desc(), TelemetryDocument.id.desc()
            )
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


# Copilot Chat Request & Route
class CopilotChatRequest(BaseModel):
    query: str
    station_id: str | None = "BHARATI"


@router.post("/api/copilot/chat")
async def copilot_chat(request: CopilotChatRequest):
    """Retrieval-Augmented Generation (RAG) Copilot assistant for telemetry queries."""
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY is not configured in server environment.",
        )

    # 1. RAG Retrieval Step: Pull recent historical measurements from database
    async with async_session() as session:
        stmt = (
            select(
                TelemetryMeasurement.timestamp,
                TelemetryMeasurement.metric,
                TelemetryMeasurement.value,
                TelemetryMeasurement.unit,
            )
            .where(TelemetryMeasurement.station_id == request.station_id)
            .order_by(TelemetryMeasurement.timestamp.desc())
            .limit(50)
        )
        result = await session.execute(stmt)
        recent_records = result.all()

    # Format telemetry context
    context_lines = [
        f"[{iso_utc(ts)}] {metric}: {value} {unit or ''}"
        for ts, metric, value, unit in recent_records
    ]
    telemetry_context = (
        "\n".join(context_lines)
        if context_lines
        else "No recent telemetry available."
    )

    # 2. System Instruction Prompting
    system_prompt = (
        "You are the Antarctic Station AI Copilot. Use the following real-time telemetry log context "
        "to answer the operator's operational or diagnostic question concisely and accurately.\n\n"
        f"--- Telemetry Context ---\n{telemetry_context}\n-----------------------"
    )

    try:
        client = genai.Client(api_key=api_key)

        def _generate():
            return client.models.generate_content(
                model="gemini-3.8-flash",
                contents=request.query,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                ),
            )

        response = await asyncio.to_thread(_generate)

        return {
            "query": request.query,
            "answer": response.text,
            "context_records_used": len(recent_records),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"LLM Copilot execution failed: {str(exc)}"
        )