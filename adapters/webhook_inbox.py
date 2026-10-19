"""Webhook sources: the platform POSTs lead events to you; we read the stored JSONL.

Run the tiny receiver (behind HTTPS / a reverse proxy in production):
    WEBHOOK_SHARED_SECRET=... python -m adapters.webhook_inbox --port 8787 --out inbox/form_leads.jsonl
Requests must carry header  X-Webhook-Secret: <secret>.

source:
  type: webhook
  path: inbox/form_leads.jsonl
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .csv_adapter import CsvAdapter


class WebhookInboxAdapter(CsvAdapter):
    """Reads the JSONL written by the receiver. Freshness = events, not file mtime."""
    type_name = "webhook"

    def fetch(self, ctx):
        cfg = dict(self.cfg)
        cfg.pop("max_age_minutes", None)
        self.cfg = cfg
        return super().fetch(ctx)


def serve(port: int, out: Path) -> None:
    secret = os.environ.get("WEBHOOK_SHARED_SECRET", "")
    if not secret:
        raise SystemExit("set WEBHOOK_SHARED_SECRET")

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            if not hmac.compare_digest(self.headers.get("X-Webhook-Secret", ""), secret):
                self.send_response(401); self.end_headers(); return
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                evt = json.loads(body)
            except ValueError:
                self.send_response(400); self.end_headers(); return
            evt.setdefault("received_at", datetime.now().astimezone().isoformat())
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(evt, ensure_ascii=False) + "\n")
            self.send_response(204); self.end_headers()

    HTTPServer(("0.0.0.0", port), H).serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--out", default="inbox/leads.jsonl")
    a = ap.parse_args()
    serve(a.port, Path(a.out))
