"""Normalized record types shared by every adapter and report."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Record:
    """One normalized row from any source.

    role=leads         -> one lead (or a pre-aggregated `count` of leads)
    role=crm           -> one CRM / sheet row filled by staff
    role=verification  -> one voucher / coupon verification (核销)
    role=response_time -> one agent's response-time summary
    """
    source_id: str
    role: str
    group: str | None            # canonical group id after alias matching
    raw_group: str = ""
    time: datetime | None = None
    kind: str = "lead"           # e.g. phone / chat / form / dm
    contact: str = ""            # normalized contact key (never rendered)
    channel: str = ""            # CRM channel value
    count: int = 1               # >1 when the source only exposes totals
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    source_id: str
    status: str                  # ok | auth_failed | stale | error | skipped
    records: list[dict] = field(default_factory=list)
    fetched_at: datetime | None = None
    message: str = ""
    evidence: dict[str, list[str]] = field(default_factory=dict)  # group -> image paths

    @property
    def ok(self) -> bool:
        return self.status == "ok"
