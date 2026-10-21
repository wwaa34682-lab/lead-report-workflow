"""platform-alert engine: config + readings -> triggered alerts + rendered messages.

Rule types (per watch):
  below            value <  threshold
  above            value >  threshold
  days_left        days = value / avg(history[-7:]); trigger if days < threshold
                   (or, when daily_budget is given, value < threshold * daily_budget)
  change_pct       pct = (value - prior) / prior * 100; trigger if |pct| >= threshold
                   (direction: up / down / any, default any)
  zero_or_missing  value is 0 / None / reading missing

Readings JSON: {"<platform>": {"login_ok": true,
                               "<metric>": {"value": 1.0, "history": [...], "prior": 1.0, "daily_budget": 0}}}
A platform with "login_ok": false yields a login_expired alert (never treated as 0).
Unreadable values / missing prior go out as type "missing" to login_expired_recipients (not the business template).
Platform names in readings that are not in the config are reported as "unknown_platform".
CLI: python evaluate.py config.yaml readings.json  -> JSON; exit 0 ok, 2 triggered, 3 data/login problem.
"""
from __future__ import annotations

import json
import math
import sys

import yaml

DEFAULT_TEMPLATES = {
    "below": "【{platform}·{metric}】当前{value}，低于{threshold}，请处理。",
    "above": "【{platform}·{metric}】当前{value}，高于{threshold}，请处理。",
    "days_left": "【{platform}·{metric}】当前{value}，按近7天消耗预计{days}天内用完，请尽快处理。",
    "change_pct": "【{platform}·{metric}】当前{value}，较上期变化{pct}%，请关注。",
    "zero_or_missing": "【{platform}·{metric}】为0或未读到，请检查。",
    "ok": "【{platform}·{metric}】{value}，正常。",
    "login_expired": "【{platform}】后台登录已失效，请尽快重新登录（{account}）。",
    "missing": "【{platform}·{metric}】今天没读到（{where}），请人工确认；不按 0 处理。",
}
PROBLEM_TYPES = ("login_expired", "missing", "unknown_platform")


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"
    return str(v)


def check(rule: dict, r: dict | None) -> dict:
    """One rule vs one reading -> {"triggered": bool, value, threshold, days, pct, ...}."""
    t, th = rule["type"], rule.get("threshold")
    v = None if r is None else r.get("value")
    out = {"value": v, "threshold": th, "days": None, "pct": None}
    if t == "zero_or_missing":
        out["triggered"] = v in (None, 0, "")
        return out
    if v is None:  # can't read the number: alert, never assume 0
        out.update(triggered=rule.get("missing_triggers", True), missing=True)
        return out
    v = float(v)
    if t == "below":
        out["triggered"] = v < th
    elif t == "above":
        out["triggered"] = v > th
    elif t == "days_left":
        hist = [float(x) for x in (r.get("history") or [])][-int(rule.get("window", 7)):]
        avg = sum(hist) / len(hist) if hist else 0.0
        budget = float(r.get("daily_budget") or rule.get("daily_budget") or 0)
        days = v / avg if avg > 0 else (v / budget if budget > 0 else math.inf)
        trig = (avg > 0 and days < th) or (budget > 0 and v < th * budget)
        out.update(avg=round(avg, 2), days_raw=None if math.isinf(days) else round(days, 2), triggered=trig,
                   days="∞" if math.isinf(days) else str(max(1, math.ceil(days)) if trig else int(days)))
    elif t == "change_pct":
        prior = r.get("prior")
        if prior in (None, ""):  # no baseline: can't compare -> report as missing, never silently pass
            out.update(triggered=True, missing=True)
            return out
        if float(prior) == 0:
            out["triggered"] = False
            return out
        pct = (v - float(prior)) / float(prior) * 100
        d = rule.get("direction", "any")
        out["pct"] = f"{pct:+.1f}"
        out["triggered"] = abs(pct) >= th and (d == "any" or (d == "up") == (pct > 0))
    else:
        raise ValueError(f"unknown rule type {t!r}")
    return out


def evaluate(cfg: dict, readings: dict) -> dict:
    alerts, oks = [], []
    for p in cfg["platforms"]:
        pr = readings.get(p["name"], {})
        if pr.get("login_ok") is False:
            tpl = (cfg.get("templates") or {}).get("login_expired", DEFAULT_TEMPLATES["login_expired"])
            alerts.append({"platform": p["name"], "metric": None, "type": "login_expired",
                           "recipients": cfg.get("login_expired_recipients", []),
                           "message": tpl.format(platform=p["name"], account=p.get("login_account") or "见配置")})
            continue
        for w in p.get("watches", []):
            res = check(w["rule"], pr.get(w["metric"]))
            if res.get("missing") and w["rule"]["type"] != "zero_or_missing":
                tpl = (cfg.get("templates") or {}).get("missing", DEFAULT_TEMPLATES["missing"])
                alerts.append({"platform": p["name"], "metric": w["metric"], "type": "missing",
                               "recipients": cfg.get("login_expired_recipients") or w.get("recipients") or [],
                               "message": tpl.format(platform=p["name"], metric=w.get("label", w["metric"]),
                                                     where=w.get("page_field") or "见配置")})
                continue
            kind = w["rule"]["type"] if res["triggered"] else "ok"
            tpls = {**DEFAULT_TEMPLATES, **(w.get("templates") or {})}
            msg = tpls[kind].format(platform=p["name"], metric=w.get("label", w["metric"]), value=_fmt(res["value"]),
                                    threshold=_fmt(res["threshold"]), days=res["days"], pct=res["pct"])
            item = {"platform": p["name"], "metric": w["metric"], "type": kind, "message": msg,
                    "recipients": w.get("recipients") or cfg.get("default_recipients", [])}
            (alerts if res["triggered"] else oks).append(item)
    known = {p["name"] for p in cfg["platforms"]}
    for k in sorted(set(readings) - known):  # 读数里的平台名在配置里不存在（多半拼错）
        alerts.append({"platform": k, "metric": None, "type": "unknown_platform",
                       "recipients": cfg.get("login_expired_recipients", []),
                       "message": f"读数里的平台「{k}」在配置中不存在（名字拼错？可选：{'、'.join(sorted(known))}）。"})
    # 有触发 -> 发触发项 + （同一接收人的）正常项作为背景；没触发 -> 只有 send_when_not_triggered 才发
    outgoing = (alerts + oks) if alerts else (oks if cfg.get("send_when_not_triggered") else [])
    msgs: dict = {}
    for a in outgoing:
        for rc in a["recipients"]:
            msgs.setdefault(rc, []).append(a["message"])
    problems = [a for a in alerts if a["type"] in PROBLEM_TYPES]
    return {"triggered": bool(alerts), "problems": bool(problems), "alerts": alerts, "ok": oks, "messages": {k: "\n".join(v) for k, v in msgs.items()}}


if __name__ == "__main__":
    cfg = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
    out = evaluate(cfg, json.load(open(sys.argv[2], encoding="utf-8")))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(3 if out["problems"] else 2 if out["triggered"] else 0)
