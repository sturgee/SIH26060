import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .database import init_db
from .mqtt_service import mqtt_listener
from .routes import manager, router
from .time_series import backfill_measurements

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_PATH = PROJECT_ROOT / "frontend"
STATIC_PATH = FRONTEND_PATH / "static"
TEMPLATES_PATH = FRONTEND_PATH / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await backfill_measurements()

    mqtt_task = asyncio.create_task(mqtt_listener(manager))
    print("[SYSTEM] Database initialized.")
    print("[SYSTEM] MQTT listener started.")

    try:
        yield
    finally:
        mqtt_task.cancel()
        try:
            await mqtt_task
        except asyncio.CancelledError:
            pass

        print("[SYSTEM] MQTT listener stopped.")


app = FastAPI(title="Energy Grid Monitor", lifespan=lifespan)

app.include_router(router)
app.mount("/static", StaticFiles(directory=str(STATIC_PATH)), name="static")


@app.get("/", include_in_schema=False)
async def read_index():
    return FileResponse(TEMPLATES_PATH / "index.html")


@app.get("/Environment", include_in_schema=False)
@app.get("/environment", include_in_schema=False)
async def serve_environment_page():
    return FileResponse(TEMPLATES_PATH / "Environment.html")


@app.get("/Generator", include_in_schema=False)
@app.get("/generator", include_in_schema=False)
async def serve_generator_page():
    return FileResponse(TEMPLATES_PATH / "Generator.html")
