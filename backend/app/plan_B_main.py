from copy import deepcopy
from datetime import datetime, timezone
import asyncio
import json
import os
from typing import Any

from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None


app = FastAPI(title="Antarctic Station Digital Twin")

stations: dict[str, dict[str, Any]] = {}
raw_telemetry: list[dict[str, Any]] = []
connections: dict[str, list[WebSocket]] = {}
STALE_SECONDS = int(os.getenv("STALE_SECONDS", "300"))


def now() -> datetime:
    return datetime.now(timezone.utc)


def calculate_state(state: dict[str, Any]) -> dict[str, Any]:
    metrics = state["metrics"]

    fuel = metrics.get("fuel_liters")
    generator_power = metrics.get("generator_power_kw")
    fuel_rate = metrics.get("fuel_rate_lph", 2.5)

    if fuel is not None and generator_power is not None:
        metrics["estimated_hours_remaining"] = round(
            fuel / max(fuel_rate * max(generator_power / 100, 0.1), 0.1), 2
        )

    alerts = []

    if fuel is not None and fuel < 500:
        alerts.append({
            "type": "low_fuel",
            "severity": "warning",
            "message": "Fuel level is low",
        })

    if metrics.get("temperature_c") is not None and metrics["temperature_c"] < -40:
        alerts.append({
            "type": "extreme_cold",
            "severity": "warning",
            "message": "Extreme external temperature",
        })

    state["alerts"] = alerts
    state["updated_at"] = now().isoformat()
    return state


async def publish(station_id: str) -> None:
    state = stations[station_id]

    for websocket in connections.get(station_id, []):
        try:
            await websocket.send_json(state)
        except Exception:
            pass


def get_or_create_station(station_id: str) -> dict[str, Any]:
    if station_id not in stations:
        stations[station_id] = {
            "station_id": station_id,
            "metrics": {},
            "quality": {},
            "alerts": [],
            "updated_at": None,
        }

    return stations[station_id]


def ingest(
    station_id: str,
    metric: str,
    value: float | int | None,
    observed_at: str | None = None,
    source: str = "api",
) -> dict[str, Any]:
    received_at = now().isoformat()
    observed_at = observed_at or received_at

    record = {
        "station_id": station_id,
        "metric": metric,
        "value": value,
        "observed_at": observed_at,
        "received_at": received_at,
        "source": source,
    }

    # Immutable raw telemetry storage.
    raw_telemetry.append(record)

    state = get_or_create_station(station_id)

    # Missing values do not overwrite the last known value.
    if value is not None:
        state["metrics"][metric] = value
        state["quality"][metric] = {
            "observed_at": observed_at,
            "received_at": received_at,
            "stale": False,
            "source": source,
        }

    return calculate_state(state)


def mark_stale() -> None:
    current_time = now()

    for state in stations.values():
        for metric, quality in state["quality"].items():
            observed = datetime.fromisoformat(
                quality["observed_at"].replace("Z", "+00:00")
            )
            quality["stale"] = (
                current_time - observed
            ).total_seconds() > STALE_SECONDS


class TelemetryMessage(BaseModel):
    station_id: str
    metric: str
    value: float | int | None = None
    observed_at: str | None = None
    source: str = "api"


class SimulationRequest(BaseModel):
    changes: dict[str, Any] = Field(default_factory=dict)


@app.get("/api/stations")
def list_stations():
    return list(stations.values())


@app.get("/api/stations/{station_id}/state")
def station_state(station_id: str):
    return get_or_create_station(station_id)


@app.get("/api/stations/{station_id}/telemetry")
def station_telemetry(station_id: str):
    return [
        item for item in raw_telemetry
        if item["station_id"] == station_id
    ]


@app.get("/api/stations/{station_id}/alerts")
def station_alerts(station_id: str):
    return get_or_create_station(station_id)["alerts"]


@app.post("/api/telemetry")
async def receive_telemetry(message: TelemetryMessage):
    state = ingest(
        station_id=message.station_id,
        metric=message.metric,
        value=message.value,
        observed_at=message.observed_at,
        source=message.source,
    )

    await publish(message.station_id)
    return state


@app.post("/api/stations/{station_id}/simulations")
def simulate(station_id: str, request: SimulationRequest):
    original = deepcopy(get_or_create_station(station_id))
    simulated = deepcopy(original)

    for metric, value in request.changes.items():
        simulated["metrics"][metric] = value
        simulated["quality"][metric] = {
            "observed_at": now().isoformat(),
            "received_at": now().isoformat(),
            "stale": False,
            "source": "simulation",
        }

    return calculate_state(simulated)


@app.websocket("/api/stations/{station_id}/stream")
async def station_stream(websocket: WebSocket, station_id: str):
    await websocket.accept()
    connections.setdefault(station_id, []).append(websocket)

    try:
        await websocket.send_json(get_or_create_station(station_id))

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connections[station_id].remove(websocket)


async def stale_worker():
    while True:
        mark_stale()
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    stale_task = asyncio.create_task(stale_worker())
    mqtt_client = start_mqtt()

    try:
        yield
    finally:
        stale_task.cancel()
        try:
            await stale_task
        except asyncio.CancelledError:
            pass

        if mqtt_client is not None:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()


app = FastAPI(
    title="Antarctic Station Digital Twin",
    lifespan=lifespan,
)


def on_mqtt_message(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode())
        ingest(
            station_id=payload["station_id"],
            metric=payload["metric"],
            value=payload.get("value"),
            observed_at=payload.get("observed_at"),
            source="mqtt",
        )
    except Exception as error:
        print(f"Invalid MQTT message: {error}")


def start_mqtt():
    if mqtt is None:
        print("MQTT disabled: install paho-mqtt to enable it")
        return None

    broker = os.getenv("MQTT_BROKER")
    if not broker:
        print("MQTT disabled: MQTT_BROKER is not configured")
        return None

    client = mqtt.Client()
    client.on_message = on_mqtt_message
    client.connect(broker, int(os.getenv("MQTT_PORT", "1883")))
    client.subscribe("stations/+/telemetry")
    client.loop_start()

    return client