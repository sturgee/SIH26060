import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import aiomqtt

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
                    print(f"MQTT Received: {payload}")
                    # Forward the raw JSON string directly to all connected WebSockets
                    await manager.broadcast(payload)
                    
        except aiomqtt.MqttError as error:
            print(f"MQTT connection error: {error}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

# --- FastAPI Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
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
            # The server must call receive() to keep the connection open 
            # and detect client disconnects, even if it only sends data.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)