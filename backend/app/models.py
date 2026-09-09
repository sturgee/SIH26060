from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class TelemetryDocument(Base):
    __tablename__ = "telemetry_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[str] = mapped_column(String(100), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class TelemetryValue(Base):
    __tablename__ = "telemetry_values"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("telemetry_documents.id", ondelete="CASCADE"),
        index=True,
    )

    # Example: energy.generators[0].status
    path: Mapped[str] = mapped_column(Text, index=True)

    value_type: Mapped[str] = mapped_column(String(20))
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_number: Mapped[float | None] = mapped_column(nullable=True)
    value_boolean: Mapped[bool | None] = mapped_column(nullable=True)
    value_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)