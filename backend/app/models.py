from datetime import datetime

from sqlalchemy import DateTime, Float, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class TelemetryLog(Base):
    __tablename__ = "telemetry_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    station_id: Mapped[str] = mapped_column(String(50), index=True)

    external_temp: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    total_power_kw: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    generator_status: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    payload: Mapped[dict] = mapped_column(JSON)