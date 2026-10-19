# adapters

| file | type | role |
|---|---|---|
| `base.py` | interface: `SourceAdapter.fetch(ctx) -> FetchResult`, `AuthError`, `StaleDataError` | — |
| `csv_adapter.py` | `csv` / `file` — CSV, XLSX, JSON, JSONL exports | any |
| `http_json.py` | `api` — generic HTTP/JSON, cursor/page pagination, auth-failure detection | any |
| `browser_manual.py` | `browser-manual` — template for page-only platforms (capture YAML + evidence) | any |
| `webhook_inbox.py` | `webhook` — JSONL inbox + minimal receiver with shared secret | leads |
| `crm_base.py` | `CrmAdapter` interface, `crm-csv`, `crm-sql` | crm |

See `docs/platforms.md` to add your own.
