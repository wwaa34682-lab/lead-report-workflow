"""Adapter interface. One adapter = one way of getting rows out of a platform.

Contract
--------
fetch(ctx) -> FetchResult
  * MUST pull live data for this run (see docs/metric-rules.md "实时重拉").
  * MUST NOT write to the platform (browse-only / read-only principle).
  * Returns raw dict rows; mapping to canonical fields happens in core.normalize via `field_map`.
  * Raises AuthError when login / token is expired so the pipeline can alert a human
    instead of reporting zeros.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime

from core.models import FetchResult


class AdapterError(Exception):
    status = "error"


class AuthError(AdapterError):
    """Login expired / QR scan needed / token rejected. Never treat as 'zero leads'."""
    status = "auth_failed"


class StaleDataError(AdapterError):
    """Data older than allowed for this run (live re-pull rule)."""
    status = "stale"


@dataclass
class FetchContext:
    data_day: date            # business day being reported
    period_start: date        # for month-to-date style reports
    now: datetime
    run_id: str
    base_dir: str


class SourceAdapter(ABC):
    type_name = "base"

    def __init__(self, source_cfg: dict, global_cfg: dict):
        self.cfg = source_cfg
        self.global_cfg = global_cfg
        self.id = source_cfg["id"]

    @abstractmethod
    def fetch(self, ctx: FetchContext) -> FetchResult: ...

    def result(self, rows, ctx: FetchContext, evidence=None, fetched_at=None, message="") -> FetchResult:
        return FetchResult(self.id, "ok", list(rows), fetched_at or ctx.now, message, evidence or {})
