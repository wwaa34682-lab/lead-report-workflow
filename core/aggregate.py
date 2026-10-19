"""Count normalized records into per-group / per-day buckets."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date

from .models import Record
from .timeutil import business_day


def _day(cfg: dict, r: Record, when=None) -> date | None:
    t = when if when is not None else r.time
    if t is None:
        return None
    start = ((cfg.get("metrics") or {}).get("day_window") or {}).get("start", "00:00")
    return business_day(t, start)


def lead_counts(cfg: dict, records: list[Record], day: date) -> dict[str, Counter]:
    """group -> Counter(kind -> count) for one business day."""
    out: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        if r.group and _day(cfg, r) == day:
            out[r.group][r.kind] += r.count
    return out


def crm_fill_counts(cfg: dict, records: list[Record], day: date, channels: list[str]) -> tuple[Counter, Counter]:
    """CRM rows for the given channels on `day`. Returns (complete, incomplete) per group.

    Channel match is exact (after strip) on purpose: '平台A' must not match '平台A-二店'.
    """
    complete, incomplete = Counter(), Counter()
    chans = {c.strip() for c in channels}
    for r in records:
        if not r.group or r.channel.strip() not in chans or _day(cfg, r) != day:
            continue
        (incomplete if r.fields.get("_missing") else complete)[r.group] += r.count
    return complete, incomplete


def daily_by_group(cfg: dict, records: list[Record], days: list[date], time_field: str | None = None) -> dict[date, Counter]:
    """day -> Counter(group -> count). time_field selects a parsed `fields[...]` datetime instead of r.time."""
    out: dict[date, Counter] = {d: Counter() for d in days}
    for r in records:
        if not r.group:
            continue
        t = r.fields.get(time_field) if time_field else r.time
        d = _day(cfg, r, t) if t is not None else None
        if d in out:
            out[d][r.group] += r.count
    return out
