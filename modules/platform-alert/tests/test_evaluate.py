import importlib.util
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(f"pa_{name}", HERE / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ev, wz = _load("evaluate"), _load("wizard")


def test_below_above():
    assert ev.check({"type": "below", "threshold": 4.5}, {"value": 4.3})["triggered"]
    assert not ev.check({"type": "below", "threshold": 4.5}, {"value": 4.8})["triggered"]
    assert ev.check({"type": "above", "threshold": 0}, {"value": 1})["triggered"]
    assert not ev.check({"type": "above", "threshold": 60}, {"value": 30})["triggered"]


def test_days_left_avg7_and_budget():
    r = ev.check({"type": "days_left", "threshold": 4}, {"value": 700, "history": [9999] + [1000] * 7})
    assert r["triggered"] and r["avg"] == 1000 and r["days"] == "1"
    r = ev.check({"type": "days_left", "threshold": 4}, {"value": 700, "history": [0] * 7, "daily_budget": 800})
    assert r["triggered"]  # no recent spend, but < 4 x budget
    r = ev.check({"type": "days_left", "threshold": 4}, {"value": 20000, "history": [2500] * 7})
    assert not r["triggered"] and r["days"] == "8"


def test_change_pct_direction():
    assert ev.check({"type": "change_pct", "threshold": 50, "direction": "down"}, {"value": 4, "prior": 10})["triggered"]
    assert not ev.check({"type": "change_pct", "threshold": 50, "direction": "down"}, {"value": 20, "prior": 10})["triggered"]
    assert ev.check({"type": "change_pct", "threshold": 50}, {"value": 20, "prior": 10})["pct"] == "+100.0"
    assert not ev.check({"type": "change_pct", "threshold": 50}, {"value": 20, "prior": 0})["triggered"]
    assert ev.check({"type": "change_pct", "threshold": 50}, {"value": 20})["missing"]  # no baseline is not "ok"


def test_zero_or_missing_and_missing_reading():
    assert ev.check({"type": "zero_or_missing"}, {"value": 0})["triggered"]
    assert ev.check({"type": "zero_or_missing"}, None)["triggered"]
    assert not ev.check({"type": "zero_or_missing"}, {"value": 3})["triggered"]
    assert ev.check({"type": "below", "threshold": 1}, None)["triggered"]  # unreadable never silently passes


def test_ad_balance_example_end_to_end():
    import json
    cfg = yaml.safe_load((HERE / "examples/ad-balance.yaml").read_text(encoding="utf-8"))
    out = ev.evaluate(cfg, json.loads((HERE / "examples/ad-balance.readings.json").read_text(encoding="utf-8")))
    assert out["triggered"]
    assert out["messages"]["财务负责人"] == "小红书当前余额¥700，预计1天内耗尽，请尽快充值。\n大众点评余额¥20,000，可用约8天，暂不需充值。"


def test_send_when_not_triggered_and_login_expired():
    cfg = {"platforms": [{"name": "P", "watches": [{"metric": "m", "rule": {"type": "below", "threshold": 1}, "recipients": ["a"]}]}],
           "login_expired_recipients": ["ops"]}
    assert ev.evaluate(cfg, {"P": {"m": {"value": 5}}})["messages"] == {}
    cfg["send_when_not_triggered"] = True
    assert ev.evaluate(cfg, {"P": {"m": {"value": 5}}})["messages"] == {"a": "【P·m】5，正常。"}
    out = ev.evaluate(cfg, {"P": {"login_ok": False}})
    assert out["alerts"][0]["type"] == "login_expired" and "ops" in out["messages"]


def test_wizard_answers_roundtrip():
    ans = yaml.safe_load((HERE / "examples/wizard-answers.example.yaml").read_text(encoding="utf-8"))
    cfg = wz.interview(ans)
    p = cfg["platforms"][0]
    assert [w["rule"]["type"] for w in p["watches"]] == ["below", "above", "change_pct"]
    assert p["watches"][1]["recipients"] == ["运营负责人", "客服群"] and cfg["login_expired_recipients"] == ["运营负责人"]
    out = ev.evaluate(cfg, {"某点评平台": {"rating": {"value": 4.2}, "bad_reviews": {"value": 0}, "leads": {"value": 10, "prior": 12}}})
    assert [a["metric"] for a in out["alerts"]] == ["rating"]


def test_missing_value_routes_to_login_contact_not_business_template():
    cfg = {"platforms": [{"name": "P", "watches": [{"metric": "bal", "label": "余额", "page_field": "财务页",
           "rule": {"type": "days_left", "threshold": 4}, "recipients": ["fin"],
           "templates": {"days_left": "余额¥{value}，{days}天"}}]}], "login_expired_recipients": ["ops"]}
    out = ev.evaluate(cfg, {"P": {}})
    assert out["problems"] and out["alerts"][0]["type"] == "missing"
    assert list(out["messages"]) == ["ops"] and "None" not in out["messages"]["ops"] and "财务页" in out["messages"]["ops"]


def test_unknown_platform_in_readings_is_reported():
    cfg = {"platforms": [{"name": "Shop", "watches": []}], "login_expired_recipients": ["ops"]}
    out = ev.evaluate(cfg, {"shop": {"x": {"value": 1}}})
    assert out["alerts"][0]["type"] == "unknown_platform" and "Shop" in out["messages"]["ops"]


def test_schedule_parsing_and_choice_aliases():
    assert wz.parse_times("工作日 9:30") == ["30 9 * * 1-5"]
    assert wz.parse_times("9:00,18:00") == ["0 9 * * *", "0 18 * * *"]
    assert wz.parse_times("每周一 8点") == ["0 8 * * 1"]
    assert wz._choice("企微", wz.CHANNELS) == "wecom" and wz._choice("2", wz.CHANNELS) == "wecom"


def test_interactive_one_platform_one_metric_is_about_12_questions(monkeypatch, capsys):
    feed = iter(["财务负责人 飞书", "n", "某平台", "主账号", "1", "财务页 → 余额", "", "", "", "n", "9:00", ""])
    monkeypatch.setattr("builtins.input", lambda *_: next(feed))
    cfg = wz.interview(None)
    asked = capsys.readouterr().out.count("[第")
    assert asked == 12
    w = cfg["platforms"][0]["watches"][0]
    assert w["rule"] == {"type": "days_left", "threshold": 4.0} and cfg["login_expired_recipients"] == ["财务负责人"]
    assert "¥" not in w["templates"]["days_left"] and "·" in w["templates"]["days_left"]
    assert cfg["platforms"][0]["url"] == "" and cfg["schedules"] == [{"cron": "0 9 * * *"}]


def test_parse_recipient():
    assert wz.parse_recipient("运营群 企微 群") == {"name": "运营群", "channel": "wecom", "target_kind": "group"}
    assert wz.parse_recipient("ops@shop.com")["channel"] == "email"
    assert wz.parse_recipient("#inv slack")["target_kind"] == "group"
