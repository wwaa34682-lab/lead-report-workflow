"""Orchestrates one run (one schedule slot, e.g. morning / evening).

fetch (live) -> normalize -> dedupe -> aggregate -> reconcile -> render -> route to recipients
Every run writes runs/<run_id>/manifest.json: source status, numbers, mismatches, evidence, deliveries.
"""
from __future__ import annotations

import json
import traceback
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import adapters
import notifiers
from adapters.base import AdapterError, FetchContext

from .aggregate import crm_fill_counts, daily_by_group, lead_counts
from .config import resolve_path
from .normalize import GroupMatcher, dedupe, normalize
from .reconcile import DASH, Table, fill_gap_table, response_time_table, verification_vs_visit
from .render import Renderer
from .timeutil import label, resolve_data_day, tz


class Run:
    def __init__(self, cfg: dict, slot: str, *, day: str | None = None, now: datetime | None = None,
                 dry_run: bool = False, only_reports: list[str] | None = None):
        self.cfg, self.slot, self.dry = cfg, slot, dry_run
        self.zone = tz(cfg)
        self.now = now or datetime.now(self.zone)
        sched = (cfg.get("schedules") or {}).get(slot)
        if sched is None:
            raise SystemExit(f"unknown schedule slot {slot!r}; defined: {list(cfg.get('schedules') or {})}")
        self.sched = sched
        self.day = resolve_data_day(day or sched.get("data_day", "yesterday"), self.now)
        ps = sched.get("period_start", "month_start")
        self.period_start = self.day.replace(day=1) if ps == "month_start" else (
            self.day - timedelta(days=int(ps[:-1]) - 1) if str(ps).endswith("d") else date.fromisoformat(ps))
        self.run_id = f"{self.day.isoformat()}-{slot}-{self.now:%H%M%S}"
        out_root = resolve_path(cfg, (cfg.get("outputs") or {}).get("dir", "runs"))
        self.out = out_root / self.run_id
        self.out.mkdir(parents=True, exist_ok=True)
        self.report_ids = only_reports or sched.get("reports") or []
        self.reports = {r["id"]: r for r in cfg.get("reports") or []}
        self.sources = {s["id"]: s for s in cfg.get("sources") or []}
        self.groups = cfg.get("groups") or {}
        self.matchers = {k: GroupMatcher(v) for k, v in self.groups.items()}
        self.fetched: dict = {}
        self.manifest: dict = {"run_id": self.run_id, "slot": slot, "data_day": self.day.isoformat(),
                               "period": [self.period_start.isoformat(), self.day.isoformat()],
                               "generated_at": self.now.isoformat(), "dry_run": dry_run,
                               "sources": {}, "reports": {}, "mismatches": [], "alerts": [], "deliveries": []}

    # ---------- fetch ----------
    def fetch(self, sid: str):
        if sid in self.fetched:
            return self.fetched[sid]
        src = self.sources[sid]
        ctx = FetchContext(self.day, self.period_start, self.now, self.run_id, self.cfg["_base_dir"])
        try:
            res = adapters.build(src, self.cfg).fetch(ctx)
        except AdapterError as e:
            res = self._fail(sid, e.status, str(e))
        except Exception as e:  # noqa: BLE001 - report, never crash the whole run
            res = self._fail(sid, "error", f"{type(e).__name__}: {e}")
            (self.out / f"error-{sid}.txt").write_text(traceback.format_exc(), encoding="utf-8")
        self.manifest["sources"][sid] = {"name": src.get("name", sid), "type": src["type"], "status": res.status,
                                         "rows": len(res.records), "message": res.message,
                                         "fetched_at": res.fetched_at.isoformat() if res.fetched_at else None}
        self.fetched[sid] = res
        return res

    def _fail(self, sid, status, msg):
        from .models import FetchResult
        src = self.sources[sid]
        self.manifest["alerts"].append({"source": sid, "name": src.get("name", sid), "status": status, "message": msg,
                                        "action": src.get("on_auth_fail_hint") or "请登录/扫码该平台后台后重跑本时段"})
        return FetchResult(sid, status, message=msg)

    def records(self, sid: str, group_set: str | None):
        res = self.fetch(sid)
        if not res.ok:
            return None, res
        src = self.sources[sid]
        gs = group_set or src.get("group_by")
        recs, stats = normalize(self.cfg, src, res.records, self.matchers.get(gs), gs)
        recs = dedupe(self.cfg, recs, src.get("dedupe"))
        self.manifest["sources"][sid].setdefault("normalize", {})[gs or "-"] = stats
        return recs, res

    # ---------- reports ----------
    def _groups(self, gs):
        return [(m["id"], m["name"]) for m in self.groups[gs]]

    def build_fill(self, r) -> tuple[list[Table], set[str]]:
        gs = r["group_by"]
        leads_recs, lres = self.records(r["source"], gs)
        crm_recs, cres = self.records(r["crm_source"], gs)
        failed = {s for s, res in ((r["source"], lres), (r["crm_source"], cres)) if not res.ok}
        cols = [((c.get("kinds") or ["*"]), c["label"]) for c in r.get("columns") or [{"label": "客资数"}]]
        leads = lead_counts(self.cfg, leads_recs or [], self.day)
        filled, incomplete = crm_fill_counts(self.cfg, crm_recs or [], self.day, r["crm_channels"])
        missing = [lbl for _, lbl in cols] if r["source"] in failed else []
        if r["crm_source"] in failed:
            filled = {g: DASH for g, _ in self._groups(gs)}
        title = r.get("title", "{date_label} {source_name} 客资填写情况").format(
            date_label=label(self.day), source_name=self.sources[r["source"]].get("name", r["source"]))
        t = fill_gap_table(title, r.get("group_label", "分组"), self._groups(gs), cols, leads, filled,
                           missing_cols=missing, incomplete=incomplete, header_color=r.get("header_color", "#E67828"),
                           total_row=r.get("total_row", False), name=r["id"])
        if r.get("record_match") and leads_recs is not None and crm_recs is not None:
            self._record_match(r, t, leads_recs, crm_recs)
        ev = lres.evidence if lres.ok else {}
        for ri, (gid, disp) in enumerate(self._groups(gs)):
            if (ri, len(t.headers) - 1) in t.red_cells:
                paths = ev.get(gid) or ev.get(disp) or []
                self.manifest["mismatches"].append({"report": r["id"], "group": disp, "row": t.rows[ri],
                                                    "evidence": paths, "evidence_missing": not paths})
        return [t], failed

    def _record_match(self, r, t: Table, leads_recs, crm_recs):
        """Optional record-level match by normalized contact key (phone / platform user id)."""
        win = int(r.get("record_match_window_days", 3))
        chans = set(r["crm_channels"])
        lo, hi = self.day - timedelta(days=win), self.day + timedelta(days=win)
        crm_keys = {c.contact for c in crm_recs if c.contact
                    and (not r.get("record_match_same_channel", True) or c.channel in chans)
                    and (c.time is None or lo <= c.time.date() <= hi)}
        un = Counter()
        for l in leads_recs:
            if l.contact and l.time and l.time.date() == self.day and l.contact not in crm_keys:
                un[l.group] += 1
        t.headers.append("未匹配(按联系方式)")
        for ri, (gid, _) in enumerate(self._groups(r["group_by"])):
            t.rows[ri].append(un.get(gid, 0))
            if un.get(gid):
                t.red_cells.add((ri, len(t.headers) - 1))
        if len(t.rows) > len(self._groups(r["group_by"])):
            t.rows[-1].append(sum(un.values()))
        t.footnotes.append(f"未匹配 = 平台有联系方式、但 CRM 中（±{win} 天内同渠道）找不到同一联系方式的客资")

    def build_reconcile(self, r):
        gs = r["group_by"]
        ver, vres = self.records(r["verification_source"], gs)
        crm, cres = self.records(r["crm_source"], gs)
        failed = {s for s, res in ((r["verification_source"], vres), (r["crm_source"], cres)) if not res.ok}
        if failed:
            return [], failed
        days = [self.period_start + timedelta(days=i) for i in range((self.day - self.period_start).days + 1)]
        crm = [c for c in crm if not r.get("visit_channels") or c.channel in r["visit_channels"]]
        vis = daily_by_group(self.cfg, crm, days, f"time_{r.get('visit_time_field', 'visit')}")
        verd = daily_by_group(self.cfg, ver, days)
        lbl = f"{label(self.period_start)}–{label(self.day)}"
        tabs = verification_vs_visit(lbl, r.get("group_label", "分组"), self._groups(gs), verd, vis, days,
                                     r.get("verification_label", "核销"), r.get("visit_label", "到店"),
                                     r.get("header_color", "#2D6EB4"))
        for t in tabs:
            t.name = f"{r['id']}-{t.name.split('-', 1)[1]}"
        bg = tabs[0]
        for ri, (gid, disp) in enumerate(self._groups(gs)):
            if (ri, 3) in bg.red_cells:
                self.manifest["mismatches"].append({"report": r["id"], "group": disp, "row": bg.rows[ri],
                                                    "evidence": [], "evidence_missing": True})
        return tabs, failed

    def build_response(self, r):
        recs, res = self.records(r["source"], r["group_by"])
        if not res.ok:
            return [], {r["source"]}
        names = dict(self._groups(r["group_by"]))
        rows = []
        for x in sorted(recs, key=lambda x: list(names).index(x.group) if x.group in names else 999):
            if x.time and x.time.date() != self.day:
                continue
            rows.append((names.get(x.group, x.raw_group), x.fields.get("agent"), x.fields.get("avg_seconds"), x.fields.get("consults")))
        title = r.get("title", "{date_label} 客服平均响应时长").format(date_label=label(self.day))
        return [response_time_table(title, r.get("group_label", "分组"), rows, r.get("threshold_seconds"),
                                    r.get("header_color", "#E67828"))], set()

    # ---------- main ----------
    def execute(self) -> dict:
        renderer = Renderer(self.cfg.get("outputs"))
        images: dict[str, list[Path]] = {}
        blocked: dict[str, list[str]] = {}
        policy = (self.cfg.get("metrics") or {}).get("on_source_failure", "hold")
        for rid in self.report_ids:
            r = self.reports[rid]
            fn = {"fill_gap": self.build_fill, "verification_vs_visit": self.build_reconcile,
                  "response_time": self.build_response}[r["type"]]
            tables, failed = fn(r)
            if failed and (policy == "hold" or not tables):
                blocked[rid] = sorted(failed)
                self.manifest["reports"][rid] = {"status": "held", "failed_sources": sorted(failed)}
                continue
            paths = [renderer.render(t, self.out / f"{t.name}.png") for t in tables]
            images[rid] = paths
            self.manifest["reports"][rid] = {"status": "rendered" + ("_with_dash" if failed else ""),
                                             "images": [str(p) for p in paths],
                                             "tables": [{"title": t.title, "headers": t.headers, "rows": t.rows,
                                                         "footnotes": t.footnotes} for t in tables]}
        self.route(images, blocked)
        (self.out / "manifest.json").write_text(json.dumps(self.manifest, ensure_ascii=False, indent=2, default=str),
                                                encoding="utf-8")
        return self.manifest

    def route(self, images, blocked):
        """Per-recipient delivery. Each recipient has their own channel, reports, format and evidence choice."""
        outbox = self.out / "outbox"
        for rc in self.cfg.get("recipients") or []:
            wants = rc.get("reports") or []
            ch = {**rc["channel"], "id": rc["id"], "target_label": rc.get("name", rc["id"])}
            batch_imgs, lines = [], []
            if self.slot in wants:
                for rid in self.report_ids:
                    if rc.get("report_ids") and rid not in rc["report_ids"]:
                        continue
                    batch_imgs += images.get(rid, [])
                if rc.get("evidence", False):
                    for m in self.manifest["mismatches"]:
                        if not rc.get("report_ids") or m["report"] in rc["report_ids"]:
                            batch_imgs += [Path(p) for p in m["evidence"] if Path(p).exists()]
                if batch_imgs:
                    lines.append(f"{label(self.day)} {self.sched.get('caption', self.slot)}：共 {len(batch_imgs)} 张图")
            if "alerts" in wants and (self.manifest["alerts"] or blocked):
                for a in self.manifest["alerts"]:
                    lines.append(f"⚠️ {a['name']} 取数失败（{a['status']}）：{a['message']} → {a['action']}")
                if blocked:
                    lines.append("以下报表已暂停发送，待重新取数后补发：" + "、".join(blocked))
            if not batch_imgs and not lines:
                continue
            fmt = rc.get("format", "image")
            caption = "\n".join(lines) if lines else None
            # alerts are always delivered as text, even to image-only recipients
            alert_only = not batch_imgs
            entry = {"recipient": rc["id"], "channel": ch["type"], "target_kind": rc.get("target_kind", "dm"),
                     "format": fmt, "images": [str(p) for p in batch_imgs], "caption": caption}
            try:
                n = notifiers.build(ch, outbox, self.dry)
                if alert_only or (fmt == "image" and caption and any(l.startswith("⚠️") for l in lines)):
                    n.deliver([], caption, "image+text")
                    if batch_imgs:
                        n.deliver(batch_imgs, None, fmt)
                else:
                    n.deliver(batch_imgs, caption, fmt)
                entry["status"] = "outbox" if (self.dry or isinstance(n, notifiers.AgentOutbox)) else "sent"
            except Exception as e:  # noqa: BLE001
                entry["status"] = f"failed: {e}"
            self.manifest["deliveries"].append(entry)
