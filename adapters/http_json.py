"""Generic HTTP/JSON API adapter (stdlib only).

source:
  type: api
  url: https://api.example.com/v1/leads           # file:// also works (used by the demo)
  method: GET
  params: {date: "{date}", page_size: 100}
  headers: {Authorization: "Bearer ${PLATFORM_X_TOKEN}"}   # secrets come from env vars
  records_path: data.items                         # dotted path to the list
  pagination: {type: cursor, cursor_param: cursor, next_path: data.next_cursor, max_pages: 50}
              # or {type: page, page_param: page, start: 1, max_pages: 50}
  auth_fail_status: [401, 403]
  auth_fail_body_contains: ["login required", "token expired"]
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .base import AuthError, FetchContext, SourceAdapter
from .csv_adapter import fill_placeholders


def dig(obj, path: str | None):
    if not path:
        return obj
    for k in path.split("."):
        if obj is None:
            return None
        obj = obj[int(k)] if isinstance(obj, list) else obj.get(k)
    return obj


class HttpJsonAdapter(SourceAdapter):
    type_name = "api"

    def _call(self, url, params, ctx):
        c = self.cfg
        method = c.get("method", "GET").upper()
        headers = {"Accept": "application/json", **{k: fill_placeholders(str(v), ctx) for k, v in (c.get("headers") or {}).items()}}
        body = None
        if url.startswith("file://"):
            req = urllib.request.Request(url)
        elif method == "GET":
            req = urllib.request.Request(url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params), headers=headers)
        else:
            body = json.dumps(params).encode()
            req = urllib.request.Request(url, data=body, method=method, headers={**headers, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=c.get("timeout", 30)) as r:
                text = r.read().decode(c.get("encoding", "utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in c.get("auth_fail_status", [401, 403]):
                raise AuthError(f"{self.id}: HTTP {e.code} — token/login expired") from e
            raise
        for marker in c.get("auth_fail_body_contains") or []:
            if marker in text:
                raise AuthError(f"{self.id}: response contains '{marker}'")
        return json.loads(text)

    def fetch(self, ctx: FetchContext):
        c = self.cfg
        url = fill_placeholders(c["url"], ctx)
        params = {k: fill_placeholders(str(v), ctx) for k, v in (c.get("params") or {}).items()}
        pag = c.get("pagination") or {}
        rows, page = [], pag.get("start", 1)
        for _ in range(pag.get("max_pages", 1) if pag else 1):
            if pag.get("type") == "page":
                params[pag.get("page_param", "page")] = page
            data = self._call(url, params, ctx)
            batch = dig(data, c.get("records_path")) or []
            rows.extend(batch)
            if pag.get("type") == "cursor":
                nxt = dig(data, pag.get("next_path"))
                if not nxt:
                    break
                params[pag.get("cursor_param", "cursor")] = nxt
            elif pag.get("type") == "page":
                if not batch:
                    break
                page += 1
            else:
                break
        return self.result(rows, ctx)
