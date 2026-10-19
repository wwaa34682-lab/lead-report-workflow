#!/usr/bin/env python3
"""lead-report-workflow CLI

  python run.py init      [--out config.yaml] [--answers answers.yaml]   # interview -> config
  python run.py validate  --config config.yaml [--check-env]            # clear error messages
  python run.py run       --config config.yaml --slot morning|evening [--date YYYY-MM-DD] [--dry-run]
  python run.py schedule  --config config.yaml                          # print crontab lines
  python run.py demo                                                    # fake data -> sample PNGs
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def cmd_validate(a) -> int:
    from core.config import load_config
    from core.validate import check

    try:
        cfg = load_config(a.config, strict=False)
    except Exception as e:  # yaml syntax etc.
        print(f"✗ 无法读取 {a.config}: {e}")
        return 2
    errors, warnings = check(cfg, a.check_env)
    for w in warnings:
        print(f"⚠ {w}")
    for e in errors:
        print(f"✗ {e}")
    if not errors:
        n = lambda k: len(cfg.get(k) or [])  # noqa: E731
        print(f"✓ 配置有效：{n('sources')} 个来源，{n('reports')} 张报表，{len(cfg.get('schedules') or {})} 个时段，{n('recipients')} 位接收人")
    return 1 if errors else 0


def cmd_run(a) -> int:
    from core.config import load_config
    from core.pipeline import Run

    cfg = load_config(a.config)
    m = Run(cfg, a.slot, day=a.date, dry_run=a.dry_run, only_reports=a.reports.split(",") if a.reports else None).execute()
    print(json.dumps({"run_id": m["run_id"], "data_day": m["data_day"],
                      "sources": {k: v["status"] for k, v in m["sources"].items()},
                      "reports": {k: v["status"] for k, v in m["reports"].items()},
                      "mismatches": len(m["mismatches"]), "alerts": len(m["alerts"]),
                      "deliveries": [(d["recipient"], d["channel"], d["status"]) for d in m["deliveries"]]},
                     ensure_ascii=False, indent=2))
    print("manifest:", Path(cfg["_base_dir"]) / (cfg.get("outputs") or {}).get("dir", "runs") / m["run_id"] / "manifest.json")
    return 3 if m["alerts"] else 0


def cmd_schedule(a) -> int:
    from core.config import load_config

    cfg = load_config(a.config)
    print(f"# crontab（时区按 {cfg.get('timezone')}，请确认服务器 TZ 或在 crontab 顶部写 CRON_TZ={cfg.get('timezone')}）")
    print(f"CRON_TZ={cfg.get('timezone')}")
    for name, s in (cfg.get("schedules") or {}).items():
        print(f"{s.get('cron', '0 9 * * *')}  cd {ROOT} && python run.py run --config {Path(a.config).resolve()} --slot {name} >> runs/cron.log 2>&1")
    return 0


def cmd_init(a) -> int:
    from core.init_wizard import run

    run(Path(a.out), Path(a.answers) if a.answers else None, ROOT / "config" / "templates")
    return 0


def cmd_demo(a) -> int:
    ex = ROOT / "examples"
    subprocess.check_call([sys.executable, str(ex / "make_fake_data.py")])
    rc = cmd_validate(argparse.Namespace(config=str(ex / "demo.yaml"), check_env=False))
    if rc:
        return rc
    for slot in ("morning", "evening"):
        cmd_run(argparse.Namespace(config=str(ex / "demo.yaml"), slot=slot, date=None, dry_run=True, reports=None))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="lead-source vs CRM daily reconciliation")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--out", default="config.yaml"); p.add_argument("--answers")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("validate"); p.add_argument("--config", required=True); p.add_argument("--check-env", action="store_true")
    p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("run"); p.add_argument("--config", required=True); p.add_argument("--slot", required=True)
    p.add_argument("--date"); p.add_argument("--dry-run", action="store_true"); p.add_argument("--reports")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("schedule"); p.add_argument("--config", required=True); p.set_defaults(fn=cmd_schedule)
    p = sub.add_parser("demo"); p.set_defaults(fn=cmd_demo)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
