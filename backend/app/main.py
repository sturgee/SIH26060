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


app = FastAPI(lifespan=lifespan)
app.include_router(router)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_PATH = PROJECT_ROOT / "frontend"
STATIC_PATH = FRONTEND_PATH / "static"

app.mount(
    "/static",
    StaticFiles(directory=STATIC_PATH),
    name="static",
)