import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .database import init_db
from .mqtt_service import mqtt_listener
from .routes import manager, router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    mqtt_task = asyncio.create_task(mqtt_listener(manager))

    try:
        yield
    finally:
        mqtt_task.cancel()

        try:
            await mqtt_task
        except asyncio.CancelledError:
            pass


# 
# ... Keep your existing imports and lifespan function exactly the same ...

app = FastAPI(lifespan=lifespan)
app.include_router(router)

# 1. Dynamically resolve absolute paths to prevent "directory not found" errors
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # Navigates up out of 'backend/app' to project root
FRONTEND_PATH = PROJECT_ROOT / "frontend"
STATIC_PATH = FRONTEND_PATH / "static"
TEMPLATES_PATH = FRONTEND_PATH / "templates"

# 2. Correctly mount the static folder using the absolute resolved path
app.mount("/static", StaticFiles(directory=str(STATIC_PATH)), name="static")

# 3. ADD THIS ROUTE: Tell FastAPI to serve index.html at the root URL (/)
from fastapi.responses import FileResponse

@app.get("/")
async def read_index():
    return FileResponse(TEMPLATES_PATH / "index.html")

@app.get("/Environment")  # <-- Change this string to whatever name you want!
async def serve_dashboard_page():
    return FileResponse(TEMPLATES_PATH / "Environment.html")
@app.get("/Generator")  # <-- Change this string to whatever name you want!
async def serve_dashboard_page():
    return FileResponse(TEMPLATES_PATH / "Generator.html")