import asyncio
import json
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import aiomqtt
from sqlalchemy import DateTime, String, Float, JSON, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# --- Database Configuration ---
DATABASE_URL = "sqlite+aiosqlite:///./telemetry.db"
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class TelemetryLog(Base):
    __tablename__ = "telemetry_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    station_id: Mapped[str] = mapped_column(String(50), index=True)
    
    # Frequently queried metrics extracted for indexing and fast analytics
    external_temp: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_power_kw: Mapped[float | None] = mapped_column(Float, nullable=True)
    generator_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    
    # Store the complete raw payload for deep nested access
    payload: Mapped[dict] = mapped_column(JSON)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def save_telemetry(payload: dict):
    """Parses key metrics and stores the telemetry document asynchronously."""
    try:
        # Extract ISO timestamp (e.g., '2026-09-08T03:00:00Z')
        raw_ts = payload.get("timestamp")
        ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00")) if raw_ts else datetime.now(timezone.utc)
        
        station_id = payload.get("station", {}).get("id", "UNKNOWN")
        ext_temp = payload.get("environment", {}).get("external_temperature", {}).get("value")
        total_power = payload.get("energy", {}).get("consumption", {}).get("total_power")
        
        # Get primary generator status
        generators = payload.get("energy", {}).get("generators", [])
        gen_status = generators[0].get("status") if generators else None

        record = TelemetryLog(
            timestamp=ts,
            station_id=station_id,
            external_temp=ext_temp,
            total_power_kw=total_power,
            generator_status=gen_status,
            payload=payload,
        )

        async with async_session() as session:
            session.add(record)
            await session.commit()
            
    except Exception as e:
        print(f"Error saving to database: {e}")

# --- WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        # Iterate over a copy of the list to safely handle disconnections during broadcast
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()

# --- Background MQTT Listener ---
async def mqtt_listener():
    # Loop ensures we attempt to reconnect if the broker drops
    while True:
        try:
            async with aiomqtt.Client("localhost") as client:
                await client.subscribe("antarctic/station/BHARATI")
                print("Connected to MQTT broker. Subscribed to 'antarctic/station/BHARATI'")
                
                async for message in client.messages:
                    payload = message.payload.decode()

                    try:
                        data = json.loads(payload)
                        # Save to DB asynchronously
                        await save_telemetry(data)
                    except json.JSONDecodeError:
                        print("Failed to decode JSON payload")
                    # Forward the raw JSON string directly to all connected WebSockets
                    await manager.broadcast(payload)
                    
        except aiomqtt.MqttError as error:
            print(f"MQTT connection error: {error}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

# --- FastAPI Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Start the MQTT background task when the server boots
    task = asyncio.create_task(mqtt_listener())
    yield
    # Clean up the task when the server shuts down
    task.cancel()

app = FastAPI(lifespan=lifespan)

# --- Frontend HTML ---
html = """
<!DOCTYPE html>
<html>
    <head>
        <title>MQTT to WebSocket</title>
        <style>
            body { font-family: sans-serif; padding: 2rem; max-width: 600px; margin: 0 auto; background: #121212; color: #fff;}
            #messages { background: #1e1e1e; padding: 1rem; border-radius: 8px; min-height: 200px; font-family: monospace; list-style-type: none; margin-top: 1rem;}
            li { border-bottom: 1px solid #333; padding: 0.75rem 0; white-space: pre-wrap;}
            .status { color: #4ade80; font-size: 0.9em; }
        </style>
    </head>
    <body>
        <h1>Live MQTT Feed</h1>
        <div class="status" id="status">Connecting to WebSocket...</div>
        <ul id="messages"></ul>
        
        <script>
            // Dynamically connect to the current host
            const ws = new WebSocket(`ws://${location.host}/ws`);
            const messagesList = document.getElementById('messages');
            const statusDiv = document.getElementById('status');
            
            ws.onopen = () => {
                statusDiv.textContent = "Connected to WebSocket!!!";
            };
            
            ws.onclose = () => {
                statusDiv.textContent = "Disconnected from WebSocket!!!";
                statusDiv.style.color = "#f87171";
            };
            
            ws.onmessage = function(event) {
                const li = document.createElement('li');
                try {
                    // Prettify the JSON if the payload is valid
                    const data = JSON.parse(event.data);
                    li.textContent = JSON.stringify(data, null, 2);
                } catch (e) {
                    // Fallback to raw text if it isn't valid JSON
                    li.textContent = event.data;
                }
                // Add new messages to the top
                messagesList.prepend(li);
            };
        </script>
    </body>
</html>
"""

@app.get("/")
async def get_frontend():
    return HTMLResponse(html)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/api/telemetry/recent")
async def get_recent_telemetry(limit: int = 10):
    """API endpoint to query recent telemetry entries from the DB."""
    async with async_session() as session:
        result = await session.execute(
            select(TelemetryLog).order_by(TelemetryLog.timestamp.desc()).limit(limit)
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