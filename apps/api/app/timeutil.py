from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, available_timezones

from app.models import utcnow


def valid_timezone(name: str) -> bool:
    return name in available_timezones()


def to_utc(day: date, at: time, tz: str) -> datetime:
    return datetime.combine(day, at, tzinfo=ZoneInfo(tz)).astimezone(UTC)


def local(dt: datetime, tz: str) -> datetime:
    return dt.astimezone(ZoneInfo(tz))


def today(tz: str, now: datetime | None = None) -> date:
    return local(now or utcnow(), tz).date()


def day_bounds_utc(day: date, tz: str) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=ZoneInfo(tz))
    end = datetime.combine(day, time.max, tzinfo=ZoneInfo(tz))
    return start.astimezone(UTC), end.astimezone(UTC)
