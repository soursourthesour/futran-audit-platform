"""Single source of 'now' so tests can move time."""
from datetime import date, datetime, timezone

_override: datetime | None = None


def utcnow() -> datetime:
    if _override is not None:
        return _override
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today() -> date:
    return utcnow().date()


def set_now(value: datetime | None) -> None:
    """Test helper: freeze 'now' (naive UTC). Pass None to unfreeze."""
    global _override
    _override = value
