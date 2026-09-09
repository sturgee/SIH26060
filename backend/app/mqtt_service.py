import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import aiomqtt
from sqlalchemy import select

from .database import async_session
from .forecasting import build_predictions
from .models import TelemetryDocument, TelemetryValue
from .websocket_manager import ConnectionManager


MQTT_HOST = "localhost"
MQTT_TOPIC = "antarctic/station/BHARATI"
HISTORY_LIMIT = 200


def flatten_json(
    value: Any,
    path: str = "",
):
    """
    Converts nested JSON into queryable key/value records.
    """

    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            yield from flatten_json(child, child_path)

    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield from flatten_json(child, child_path)

    else:
        if value is None:
            value_type = "null"
        elif isinstance(value, bool):
            value_type = "boolean"
        elif isinstance(value, (int, float)):
            value_type = "number"
        elif isinstance(value, str):
            value_type = "string"
        else:
            value_type = "json"

        yield {
            "path": path,
            "value_type": value_type,
            "value_text": value if value_type == "string" else None,
            "value_number": (
                float(value)
                if value_type == "number"
                else None
            ),
            "value_boolean": (
                value
                if value_type == "boolean"
                else None
            ),
            "value_json": (
                value
                if value_type in {"null", "json"}
                else None
            ),
        }


def parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)

    try:
        timestamp = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        return timestamp

    except ValueError:
        return datetime.now(timezone.utc)


def get_station_id(payload: dict[str, Any]) -> str:
    return (
        payload.get("station", {}).get("id")
        or payload.get("station_id")
        or "UNKNOWN"
    )


async def save_telemetry(payload: dict[str, Any]) -> None:
    timestamp = parse_timestamp(payload.get("timestamp"))
    received_at = datetime.now(timezone.utc)
    station_id = get_station_id(payload)

    async with async_session() as session:
        document = TelemetryDocument(
            station_id=station_id,
            timestamp=timestamp,
            received_at=received_at,
            payload=payload,
        )

        session.add(document)
        await session.flush()

        for item in flatten_json(payload):
            session.add(
                TelemetryValue(
                    document_id=document.id,
                    **item,
                )
            )

        await session.commit()


async def load_numeric_history(
    station_id: str,
) -> dict[str, list[tuple[datetime, float]]]:
    async with async_session() as session:
        query = (
            select(
                TelemetryValue.path,
                TelemetryDocument.timestamp,
                TelemetryValue.value_number,
            )
            .join(
                TelemetryDocument,
                TelemetryDocument.id == TelemetryValue.document_id,
            )
            .where(
                TelemetryDocument.station_id == station_id,
                TelemetryValue.value_type == "number",
                TelemetryValue.value_number.is_not(None),
            )
            .order_by(
                TelemetryValue.path,
                TelemetryDocument.timestamp,
            )
        )

        result = await session.execute(query)
        rows = result.all()

    history: dict[str, list[tuple[datetime, float]]] = {}

    for path, timestamp, value in rows:
        values = history.setdefault(path, [])

        if len(values) < HISTORY_LIMIT:
            values.append((timestamp, float(value)))
        else:
            values.pop(0)
            values.append((timestamp, float(value)))

    return history


async def process_telemetry(
    payload: dict[str, Any],
) -> dict[str, Any]:
    await save_telemetry(payload)

    station_id = get_station_id(payload)
    history = await load_numeric_history(station_id)
    predictions = build_predictions(history, steps=5)

    outgoing_payload = dict(payload)
    outgoing_payload["predictions"] = predictions

    return outgoing_payload


async def mqtt_listener(manager: ConnectionManager) -> None:
    while True:
        try:
            async with aiomqtt.Client(MQTT_HOST) as client:
                await client.subscribe(MQTT_TOPIC)

                print(
                    f"Connected to MQTT broker. "
                    f"Subscribed to '{MQTT_TOPIC}'"
                )

                async for message in client.messages:
                    raw_payload = message.payload.decode()

                    try:
                        data = json.loads(raw_payload)
                    except json.JSONDecodeError:
                        print("Failed to decode JSON payload")
                        continue

                    try:
                        outgoing_payload = await process_telemetry(data)
                    except Exception as error:
                        print(f"Failed to process telemetry: {error}")
                        continue

                    await manager.broadcast(
                        json.dumps(
                            outgoing_payload,
                            separators=(",", ":"),
                        )
                    )

        except asyncio.CancelledError:
            raise

        except aiomqtt.MqttError as error:
            print(
                f"MQTT connection error: {error}. "
                "Retrying in 5 seconds..."
            )
            await asyncio.sleep(5)