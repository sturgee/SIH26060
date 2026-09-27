# SIH26060 — Energy Grid Monitor

## Run the live telemetry dashboard

The application stores telemetry timestamps in **UTC** and displays all dashboard times in **IST (Asia/Kolkata)**.

### 1. Install dependencies

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Start an MQTT broker

The backend and simulator use `localhost:1883` and topic `antarctic/station/BHARATI`.
Make sure an MQTT broker (for example Mosquitto) is running on port 1883.

### 3. Start the FastAPI backend

From the project root:

```
python -m uvicorn backend.app.main:app --reload
```

Open `http://127.0.0.1:8000`.

### 4. Start the simulator in a second terminal

From the project root:

```
python station_simulator.py
```

You should see the simulator publishing to `antarctic/station/BHARATI`. The dashboard receives those packets through the backend WebSocket and stores them in SQLite.

## Time handling

- Database: UTC
- API: UTC ISO-8601 with `Z`
- Dashboard: IST
- Historical `datetime-local` inputs: interpreted as IST, converted to UTC for API queries

If the WebSocket is temporarily unavailable, the frontend also polls `/api/telemetry/latest` so the latest stored MQTT packet can still populate the dashboard.
