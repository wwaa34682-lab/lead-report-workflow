"""Map raw adapter rows to `Record`s, apply 口径 (metric) rules.

Rules are driven by config `metrics` (global) merged with per-source overrides:
  - field_map            raw column -> canonical field
  - group matching       exact name / id / alias, then unique substring; ambiguous -> unmatched
  - valid_lead filters   drop rows that are not valid leads (test, spam, duplicates...)
  - required_fields      CRM rows missing these are reported as incomplete, not counted as filled
  - dedupe               one contact counts once per (source, group, day)
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any

from .models import Record
from .timeutil import business_day, parse_dt, tz

CANON = ("id", "group", "time", "kind", "contact", "channel", "count")


def _get(row: dict, key: str | None) -> Any:
    if not key:
        return None
    if key in row:
        return row[key]
    cur: Any = row
    for part in key.split("."):          # dotted path for nested JSON
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


class GroupMatcher:
    def __init__(self, members: list[dict]):
        self.members = members
        self.exact: dict[str, str] = {}
        for m in members:
            for k in [m["id"], m["name"], *(m.get("aliases") or [])]:
                self.exact[str(k).strip()] = m["id"]

    def match(self, raw: Any) -> str | None:
        s = "" if raw is None else str(raw).strip()
        if not s:
            return None
        if s in self.exact:
            return self.exact[s]
        hits = {gid for key, gid in self.exact.items() if key and key in s}
        return hits.pop() if len(hits) == 1 else None   # ambiguous / unknown -> None

    def name(self, gid: str) -> str:
        return next((m["name"] for m in self.members if m["id"] == gid), gid)


def contact_key(value: Any, salt: str = "") -> str:
    """Normalize a phone / user id into an opaque key. Raw contacts never leave this function."""
    if value in (None, ""):
        return ""
    s = str(value).strip()
    digits = re.sub(r"\D", "", s)
    base = digits[-11:] if len(digits) >= 7 else s.lower()
    return hashlib.sha256((salt + base).encode()).hexdigest()[:16]


_OPS = {
    "eq": lambda a, b: str(a) == str(b),
    "ne": lambda a, b: str(a) != str(b),
    "in": lambda a, b: str(a) in [str(x) for x in b],
    "not_in": lambda a, b: str(a) not in [str(x) for x in b],
    "contains": lambda a, b: str(b) in str(a or ""),
    "not_contains": lambda a, b: str(b) not in str(a or ""),
    "gte": lambda a, b: a not in (None, "") and float(a) >= float(b),
    "lte": lambda a, b: a not in (None, "") and float(a) <= float(b),
    "empty": lambda a, b: (a in (None, "")) == bool(b),
}


def passes(row: dict, rules: list[dict]) -> bool:
    for r in rules or []:
        val = _get(row, r["field"])
        if not _OPS[r.get("op", "eq")](val, r.get("value")):
            return False
    return True


def normalize(cfg: dict, source: dict, rows: list[dict], matcher: GroupMatcher | None,
              group_set: str | None = None) -> tuple[list[Record], dict]:
    """group_set: for CRM sources with `group_fields` (e.g. stores -> 门店, people -> 创建人)."""
    zone = tz(cfg)
    metrics = cfg.get("metrics") or {}
    fmap = dict(source.get("field_map") or {})
    if group_set and (source.get("group_fields") or {}).get(group_set):
        fmap["group"] = source["group_fields"][group_set]
    tfmt = source.get("time_format")
    salt = metrics.get("contact_salt", "")
    filters = list(metrics.get("valid_lead", {}).get("filters") or []) if source["role"] == "leads" else []
    filters += source.get("filters") or []
    required = source.get("required_fields")
    if required is None and source["role"] == "crm":
        required = metrics.get("required_fields") or []
    attribution = source.get("date_attribution") or metrics.get("date_attribution", "first_contact")
    time_key = (source.get("time_fields") or {}).get(attribution) or fmap.get("time", "time")
    stats = {"raw": len(rows), "filtered": 0, "unmatched_group": 0, "incomplete": 0, "unmatched_samples": []}
    out: list[Record] = []
    for row in rows:
        if not passes(row, filters):
            stats["filtered"] += 1
            continue
        raw_group = _get(row, fmap.get("group", "group"))
        gid = matcher.match(raw_group) if matcher else None
        if matcher and gid is None:
            stats["unmatched_group"] += 1
            if len(stats["unmatched_samples"]) < 5:
                stats["unmatched_samples"].append(str(raw_group))
        extra = {k: _get(row, v) for k, v in fmap.items() if k not in CANON}
        for k, v in (source.get("time_fields") or {}).items():
            extra[f"time_{k}"] = parse_dt(_get(row, v), zone, tfmt)
        missing = [f for f in required or [] if _get(row, fmap.get(f, f)) in (None, "")]
        if missing:
            stats["incomplete"] += 1
            extra["_missing"] = missing
        cnt = _get(row, fmap.get("count", "count"))
        out.append(Record(
            source_id=source["id"],
            role=source["role"],
            group=gid,
            raw_group="" if raw_group is None else str(raw_group),
            time=parse_dt(_get(row, time_key), zone, tfmt),
            kind=str(_get(row, fmap.get("kind", "kind")) or source.get("default_kind", "lead")),
            contact=contact_key(_get(row, fmap.get("contact", "contact")), salt),
            channel=str(_get(row, fmap.get("channel", "channel")) or ""),
            count=int(cnt) if cnt not in (None, "") else 1,
            fields=extra,
        ))
    return out, stats


def dedupe(cfg: dict, records: list[Record], scope: str | None = None) -> list[Record]:
    """Keep the earliest record per (source, group, business-day, contact).

    scope: day (default) | window (whole run) | none. Records without a contact
    key or pre-aggregated counts are never deduped.
    """
    metrics = cfg.get("metrics") or {}
    scope = scope or (metrics.get("dedupe") or {}).get("scope", "day")
    if scope == "none":
        return records
    start = (metrics.get("day_window") or {}).get("start", "00:00")
    seen: set = set()
    out = []
    for r in sorted(records, key=lambda r: (r.time is None, r.time)):
        if not r.contact or r.count != 1:
            out.append(r)
            continue
        d = business_day(r.time, start) if (scope == "day" and r.time) else None
        key = (r.source_id, r.group, d, r.contact)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def by_group(records: list[Record]) -> dict[str | None, list[Record]]:
    d: dict[str | None, list[Record]] = defaultdict(list)
    for r in records:
        d[r.group].append(r)
    return d
