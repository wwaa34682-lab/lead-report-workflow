"""Adapter registry. `type` in config -> class. Custom: type: custom, class: "my_pkg.mod:MyAdapter"."""
from __future__ import annotations

import importlib

from .base import AdapterError, AuthError, FetchContext, SourceAdapter, StaleDataError
from .browser_manual import BrowserManualAdapter
from .crm_base import CrmAdapter, CsvCrmAdapter, SqlCrmAdapter
from .csv_adapter import CsvAdapter
from .http_json import HttpJsonAdapter
from .webhook_inbox import WebhookInboxAdapter

REGISTRY = {
    "csv": CsvAdapter,
    "file": CsvAdapter,
    "api": HttpJsonAdapter,
    "http-json": HttpJsonAdapter,
    "browser-manual": BrowserManualAdapter,
    "webhook": WebhookInboxAdapter,
    "crm-csv": CsvCrmAdapter,
    "crm-sql": SqlCrmAdapter,
}


def build(source_cfg: dict, global_cfg: dict) -> SourceAdapter:
    t = source_cfg["type"]
    if t == "custom":
        mod, cls = source_cfg["class"].split(":")
        return getattr(importlib.import_module(mod), cls)(source_cfg, global_cfg)
    if t not in REGISTRY:
        raise ValueError(f"unknown source type {t!r}; known: {sorted(REGISTRY)} or 'custom'")
    return REGISTRY[t](source_cfg, global_cfg)


__all__ = ["build", "REGISTRY", "SourceAdapter", "CrmAdapter", "FetchContext", "AdapterError", "AuthError", "StaleDataError"]
