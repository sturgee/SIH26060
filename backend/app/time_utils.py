"""UTC storage and India Standard Time (IST) display helpers."""
from datetime import datetime, timezone

IST_OFFSET_MINUTES = 330


def ensure_utc(value: datetime | None) -> datetime | None:
    """Return an aware UTC datetime. SQLite may return naive UTC values."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso_utc(value: datetime | None) -> str | None:
    """Serialize a timestamp unambiguously as UTC with a trailing Z."""
    value = ensure_utc(value)
    if value is None:
        return None
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")
