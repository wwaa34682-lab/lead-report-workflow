"""CRM adapter interface — the "system of record" side of the reconciliation.

Any CRM works as long as it can return one row per customer record with at least:
  channel  (获客渠道 / lead source)   -> matched EXACTLY to each lead source's `crm_channels`
  group    (store / owner / team)     -> matched via groups + aliases
  time     (first-contact time by default; see metrics.date_attribution)
optional: contact (phone / platform user id, for record-level matching), visit time, owner...

Implementations: CsvCrmAdapter below (spreadsheet / any CRM's export). For live APIs
(Feishu Bitable, Salesforce SOQL, HubSpot CRM search, a SQL view...) subclass CrmAdapter,
implement `fetch_rows`, and keep it read-only. See docs/platforms.md for sketches.
"""
from __future__ import annotations

from abc import abstractmethod

from .base import FetchContext, SourceAdapter
from .csv_adapter import CsvAdapter


class CrmAdapter(SourceAdapter):
    """role: crm. Pull rows covering at least [period_start, data_day] (+1 day margin)."""

    @abstractmethod
    def fetch_rows(self, ctx: FetchContext) -> list[dict]: ...

    def fetch(self, ctx: FetchContext):
        return self.result(self.fetch_rows(ctx), ctx)


class CsvCrmAdapter(CrmAdapter):
    """CRM exported to CSV/XLSX/JSON (Bitable export, Salesforce report export, HubSpot export, Excel...)."""
    type_name = "crm-csv"

    def fetch_rows(self, ctx):
        return CsvAdapter(self.cfg, self.global_cfg).fetch(ctx).records

    def fetch(self, ctx):
        res = CsvAdapter(self.cfg, self.global_cfg).fetch(ctx)   # keeps mtime freshness check
        res.source_id = self.id
        return res


class SqlCrmAdapter(CrmAdapter):
    """Read-only SQL view. source: {type: crm-sql, dsn_env: CRM_DSN, query: "select ... where day between :start and :end"}
    Uses SQLAlchemy if installed (optional dependency)."""
    type_name = "crm-sql"

    def fetch_rows(self, ctx):
        import os

        try:
            import sqlalchemy as sa
        except ImportError as e:
            raise RuntimeError("pip install sqlalchemy (+ DB driver) for crm-sql") from e
        eng = sa.create_engine(os.environ[self.cfg["dsn_env"]])
        with eng.connect() as c:
            res = c.execute(sa.text(self.cfg["query"]), {"start": ctx.period_start.isoformat(), "end": ctx.data_day.isoformat()})
            return [dict(r._mapping) for r in res]
