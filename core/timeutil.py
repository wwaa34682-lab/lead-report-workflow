from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def tz(cfg: dict) -> ZoneInfo:
    return ZoneInfo(cfg.get("timezone", "UTC"))


def parse_dt(value, zone: ZoneInfo, fmt: str | None = None) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        v = float(value)
        dt = datetime.fromtimestamp(v / 1000 if v > 1e11 else v, zone)
    else:
        s = str(value).strip()
        if fmt:
            dt = datetime.strptime(s, fmt)
        else:
            s = s.replace("/", "-").replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(s)
            except ValueError:
                dt = datetime.strptime(s[:10], "%Y-%m-%d")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone)
    return dt.astimezone(zone)


def day_window(day: date, zone: ZoneInfo, start: str = "00:00") -> tuple[datetime, datetime]:
    h, m = (int(x) for x in start.split(":"))
    s = datetime.combine(day, time(h, m), zone)
    return s, s + timedelta(days=1)


def business_day(dt: datetime, start: str = "00:00") -> date:
    h, m = (int(x) for x in start.split(":"))
    return (dt - timedelta(hours=h, minutes=m)).date()


def resolve_data_day(spec: str, now: datetime) -> date:
    """spec: today | yesterday | YYYY-MM-DD"""
    if spec == "today":
        return now.date()
    if spec == "yesterday":
        return now.date() - timedelta(days=1)
    return date.fromisoformat(spec)


def label(d: date) -> str:
    return f"{d.month}月{d.day}日"
