import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

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