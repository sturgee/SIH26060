import asyncio
import json
from datetime import datetime, timezone

import aiomqtt

from .database import async_session
from .models import TelemetryLog
from .websocket_manager import ConnectionManager


MQTT_HOST = "localhost"
MQTT_TOPIC = "antarctic/station/BHARATI"


async def save_telemetry(payload: dict) -> None:
    try:
        raw_timestamp = payload.get("timestamp")

        timestamp = (
            datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
            if raw_timestamp
            else datetime.now(timezone.utc)
        )

        station_id = payload.get("station", {}).get("id", "UNKNOWN")

        external_temp = (
            payload.get("environment", {})
            .get("external_temperature", {})
            .get("value")
        )

        total_power = (
            payload.get("energy", {})
            .get("consumption", {})
            .get("total_power")
        )

        generators = payload.get("energy", {}).get("generators", [])
        generator_status = generators[0].get("status") if generators else None

        record = TelemetryLog(
            timestamp=timestamp,
            station_id=station_id,
            external_temp=external_temp,
            total_power_kw=total_power,
            generator_status=generator_status,
            payload=payload,
        )

        async with async_session() as session:
            session.add(record)
            await session.commit()

    except Exception as error:
        print(f"Error saving telemetry: {error}")


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

                    await save_telemetry(data)
                    await manager.broadcast(raw_payload)

        except asyncio.CancelledError:
            raise

        except aiomqtt.MqttError as error:
            print(
                f"MQTT connection error: {error}. "
                "Retrying in 5 seconds..."
            )
            await asyncio.sleep(5)