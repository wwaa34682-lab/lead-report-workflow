"""Template adapter for platforms without an API or export: browser-assisted / manual capture.

A human or an AI agent opens the platform back-office in a browser (read-only: never click
"reply", "edit", "export to third party", etc.), reads the numbers and saves a capture file:

  captures/<source_id>/<YYYY-MM-DD>.yaml       (template: examples/manual-capture.template.yaml)

  fetched_at: 2026-03-10T21:05:00+08:00   # when the page was read — must be from THIS run
  captured_by: agent                       # agent | human name/role
  status: ok                               # ok | auth_failed (login/QR expired)
  page: "后台 > 客资管理 > 线索列表"          # where it was read (no URLs with tokens!)
  counts:                                  # aggregate numbers shown on the page
    - {group: A店, kind: phone, count: 2}
  records: []                              # or row-level data if the page lists rows
  evidence:                                # screenshots, required for any group with a gap
    A店: [evidence/<source_id>/A店-list.png]

source:
  type: browser-manual
  capture_dir: captures/{source_id}
  max_age_minutes: 90      # live re-pull rule: older captures are rejected
"""
from __future__ import annotations

from pathlib import Path

import yaml

from core.config import resolve_path
from core.timeutil import parse_dt

from .base import AuthError, FetchContext, SourceAdapter, StaleDataError


class BrowserManualAdapter(SourceAdapter):
    type_name = "browser-manual"

    def fetch(self, ctx: FetchContext):
        d = resolve_path(self.global_cfg, self.cfg.get("capture_dir", "captures/{source_id}").format(source_id=self.id))
        path = d / f"{ctx.data_day.isoformat()}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"{self.id}: no capture for {ctx.data_day} at {path} — open the platform and capture it")
        cap = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if cap.get("status") == "auth_failed":
            raise AuthError(f"{self.id}: capture reports login expired — {cap.get('message', 'scan / re-login needed')}")
        fetched = parse_dt(cap.get("fetched_at"), ctx.now.tzinfo)
        if fetched is None:
            raise StaleDataError(f"{self.id}: capture has no fetched_at")
        max_age = self.cfg.get("max_age_minutes")
        if max_age and (ctx.now - fetched).total_seconds() > max_age * 60:
            raise StaleDataError(f"{self.id}: capture is from {fetched:%m-%d %H:%M}, older than {max_age} min — re-pull live")
        rows = list(cap.get("records") or [])
        for c in cap.get("counts") or []:
            rows.append({"time": c.get("time") or f"{ctx.data_day}T12:00:00", **c})
        evidence = {g: [str(resolve_path(self.global_cfg, p)) for p in ps] for g, ps in (cap.get("evidence") or {}).items()}
        return self.result(rows, ctx, evidence=evidence, fetched_at=fetched, message=f"captured_by={cap.get('captured_by', '?')}")
