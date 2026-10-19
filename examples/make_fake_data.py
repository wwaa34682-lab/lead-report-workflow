#!/usr/bin/env python3
"""Generate FULLY FAKE demo data (no real stores / people / phones / platforms).

Dates are relative to "now" so the live re-pull freshness checks pass:
  month-to-date up to today, captures stamped with the current time.
Fake contacts use the 100xxxxxxxx pattern, which is not a valid mobile number range.
"""
from __future__ import annotations

import csv
import json
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

HERE = Path(__file__).resolve().parent
D = HERE / "data"
TZ = ZoneInfo("Asia/Shanghai")
STORES = ["A店", "B店", "C店", "D店", "E店"]
PEOPLE = ["员工甲", "员工乙", "员工丙", "员工丁"]
rng = random.Random(20260101)
_seq = iter(range(1, 10**6))


def phone() -> str:
    return f"100{next(_seq):08d}"


def ts(d: date, lo=9, hi=21) -> datetime:
    return datetime.combine(d, time(rng.randint(lo, hi - 1), rng.randint(0, 59)), TZ)


def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


def main():
    now = datetime.now(TZ)
    today = now.date()
    start = (today - timedelta(days=1)).replace(day=1)          # covers yesterday's month too
    days = [start + timedelta(days=i) for i in range((today - start).days + 1)]
    social, review, form, crm, vouchers, cs = [], [], [], [], [], []

    def to_crm(channel, store, owner, t, contact, p_fill=0.8):
        if rng.random() > p_fill:
            return
        crm.append({"客户编号": f"C{len(crm) + 1:05d}", "获客渠道": channel, "门店": store, "创建人": owner,
                    "首次咨询时间": t.strftime("%Y-%m-%d %H:%M:%S"),
                    "创建时间": (t + timedelta(minutes=rng.randint(5, 600))).strftime("%Y-%m-%d %H:%M:%S"),
                    "手机号": contact, "到店时间": "", "备注": ""})

    for d in days:
        for p in PEOPLE:                                     # 社媒平台X: per-person DMs
            for _ in range(rng.choice([0, 0, 1, 1, 2, 3])):
                t, c = ts(d), phone()
                social.append({"lead_id": f"S{len(social) + 1:05d}", "owner": p, "created_at": t.isoformat(),
                               "contact": c, "status": "valid" if rng.random() > 0.1 else "test"})
                to_crm("社媒平台X", rng.choice(STORES), p, t, c, 0.75)
        for s in STORES:                                     # 点评类平台Y: phone + chat per store
            for kind in ("phone", "chat"):
                for _ in range(rng.choice([0, 1, 1, 2, 3])):
                    t, c = ts(d), phone()
                    review.append({"id": f"R{len(review) + 1:05d}", "shop": {"name": s}, "type": kind,
                                   "created_at": t.isoformat(), "mobile": c})
                    to_crm("点评类平台Y", s, rng.choice(PEOPLE), t, c, 0.8)
            for _ in range(rng.choice([0, 0, 1])):           # 官网表单 webhook
                t, c = ts(d), phone()
                form.append({"event": "lead.created", "store": s, "submitted_at": t.isoformat(), "phone": c})
                to_crm("官网表单", s, rng.choice(PEOPLE), t, c, 0.9)
            n_ver = rng.choice([0, 1, 1, 2, 3])              # 团购核销 vs 到店
            for _ in range(n_ver):
                t = ts(d, 10, 22)
                vouchers.append({"voucher_no": f"V{len(vouchers) + 1:06d}", "store": s, "verified_at": t.isoformat(),
                                 "product": "体验课（示例）"})
            visits = max(n_ver - (1 if rng.random() < 0.2 else 0), 0) + (1 if rng.random() < 0.1 else 0)
            for _ in range(visits):
                t = ts(d, 10, 22)
                crm.append({"客户编号": f"C{len(crm) + 1:05d}", "获客渠道": "点评类平台Y", "门店": s,
                            "创建人": rng.choice(PEOPLE), "首次咨询时间": (t - timedelta(days=rng.randint(1, 5))).strftime("%Y-%m-%d %H:%M:%S"),
                            "创建时间": (t - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"), "手机号": phone(),
                            "到店时间": t.strftime("%Y-%m-%d %H:%M:%S"), "备注": ""})
        for s in STORES:                                     # 客服响应时长
            cs.append({"date": d.isoformat(), "store": s, "agent": f"客服{STORES.index(s) + 1:02d}",
                       "avg_seconds": rng.choice([25, 48, 75, 130, 210, 420]), "consults": rng.randint(1, 15)})
    # a few incomplete CRM rows (missing 门店) -> counted as 缺必填, not filled
    for r in rng.sample(crm, 3):
        r["门店"] = ""

    write_csv(D / "social_x_leads.csv", social)
    (D / "review_y_api.json").write_text(json.dumps({"code": 0, "data": {"items": review, "next_cursor": None}},
                                                    ensure_ascii=False, indent=1), encoding="utf-8")
    (D / "form_leads.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in form), encoding="utf-8")
    write_csv(D / "crm_export.csv", crm)
    write_csv(D / "vouchers.csv", vouchers)
    write_csv(D / "cs_response.csv", cs)

    # 地图平台Z: browser-assisted manual capture (one file per data day) + a fake evidence screenshot
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ev_dir = HERE / "evidence" / "map_z"
    ev_dir.mkdir(parents=True, exist_ok=True)
    for d in (today - timedelta(days=1), today):
        counts = [{"group": s, "kind": "lead", "count": rng.choice([0, 1, 2, 3]), "time": f"{d}T12:00:00+08:00"} for s in STORES]
        counts[1]["count"] = 3                                # make B店 likely show a gap
        for c in counts:
            for _ in range(max(c["count"] - (1 if c["group"] == "B店" else 0), 0)):
                to_crm("地图平台Z", c["group"], rng.choice(PEOPLE), ts(d), phone(), 1.0)
        shot = ev_dir / f"{d}-B店-list.png"
        fig = plt.figure(figsize=(4, 2.2), dpi=100)
        fig.text(0.5, 0.6, "示例证据截图（假数据）\n地图平台Z › 客资列表 › B店", ha="center", va="center",
                 fontsize=11, family="Noto Sans CJK SC")
        fig.text(0.5, 0.2, f"{d}  共 3 条", ha="center", fontsize=9, family="Noto Sans CJK SC", color="#666")
        fig.savefig(shot); plt.close(fig)
        cap = {"fetched_at": now.isoformat(timespec="seconds"), "captured_by": "agent", "status": "ok",
               "page": "地图平台Z 商家后台 > 客资管理 > 客资列表（示例）", "counts": counts,
               "evidence": {"B店": [str(shot.relative_to(HERE))]}}
        p = HERE / "captures" / "map_z" / f"{d}.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(cap, allow_unicode=True, sort_keys=False), encoding="utf-8")
    write_csv(D / "crm_export.csv", crm)
    print(f"fake data: {len(social)} social, {len(review)} review, {len(form)} form, {len(crm)} crm rows, "
          f"{len(vouchers)} vouchers, {len(days)} days ({days[0]}..{days[-1]})")


if __name__ == "__main__":
    main()
