"""platform-alert 询问式配置向导：一次只问一个问题 -> 写出 platform-alert.yaml。

python modules/platform-alert/wizard.py [--answers answers.yaml] [--out platform-alert.yaml]
--answers 模式下答案从文件读（键 = 每个 ask() 的第一个参数），供 AI 助手在聊天里逐题问完后批量写入。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

CHANNELS = {"feishu": "飞书", "wecom": "企业微信", "dingtalk": "钉钉", "wechat": "个人微信（助手代发）", "slack": "Slack", "email": "Email"}
CHANNEL_ALIAS = {"飞书": "feishu", "lark": "feishu", "企微": "wecom", "企业微信": "wecom", "钉钉": "dingtalk",
                 "微信": "wechat", "邮件": "email", "邮箱": "email", "mail": "email"}
METRICS = {"balance": "余额（可配可用天数）", "spend": "花费/消耗", "leads": "客资/留资数", "response_time": "客服响应时长",
           "rating": "评分", "bad_reviews": "差评数", "inventory": "库存", "custom": "页面上任意一个数"}
RULES = {"below": "低于阈值", "above": "高于阈值", "days_left": "可用天数 = 值 ÷ 近7天日均（低于N天）",
         "change_pct": "较上期变化超过N%", "zero_or_missing": "为0或读不到"}
DEFAULT_RULE = {"balance": "days_left", "spend": "above", "leads": "zero_or_missing", "response_time": "above",
                "rating": "below", "bad_reviews": "above", "inventory": "below", "custom": "below"}
DEFAULT_TPL = {"days_left": "【{platform}·{metric}】当前{value}，按近7天消耗预计{days}天内用完，请尽快处理。",
               "ok_days_left": "【{platform}·{metric}】当前{value}，可用约{days}天，暂不需处理。"}
THRESHOLD_HINT = {"days_left": "天数", "change_pct": "百分比：30 = 下降超过30%提醒，-30 = 上涨超过30%提醒", "below": "数值", "above": "数值"}
WEEKDAYS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 0, "天": 0}


class Asker:
    """问一个问题。交互模式下答错会重问（不会整个退出）；可选项可填序号或键名或中文名。"""

    def __init__(self, answers, counter=None):
        self.answers = answers
        self.counter = counter if counter is not None else [0]

    def __call__(self, key, prompt, default=None, choices=None, multi=False, validate=None, example=None):
        while True:
            if self.answers is not None:
                v = self.answers.get(key, default)
            else:
                self.counter[0] += 1
                print(f"\n[第{self.counter[0]}问] {prompt}")
                if example:
                    print(f"    例：{example}")
                if choices:
                    for i, (k, d) in enumerate(choices.items(), 1):
                        print(f"    {i}. {k} — {d}")
                dflt = f"（回车 = {default}）" if default not in (None, "") else ""
                v = input(f"  {dflt}> ").strip() or default
            try:
                if multi and isinstance(v, str):
                    v = [x.strip() for x in re.split(r"[,，、\s]+", v) if x.strip()]
                if choices and not multi:
                    v = _choice(v, choices)
                if validate:
                    v = validate(v)
                return v
            except ValueError as e:
                if self.answers is not None:
                    raise SystemExit(f"{key}: {e}")
                print(f"  ✗ {e}，请重新输入")


def _choice(v, choices):
    s = str(v).strip() if v is not None else ""
    s = CHANNEL_ALIAS.get(s.lower(), s)
    if s.isdigit() and 1 <= int(s) <= len(choices):
        return list(choices)[int(s) - 1]
    for k, d in choices.items():
        if s.lower() == k or (s and s == d.split("（")[0]):
            return k
    raise ValueError(f"「{v}」不是可选项（可填序号或 {'/'.join(choices)}）")


def _int(v):
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        raise ValueError(f"请填整数，「{v}」不是")
    if n < 1:
        raise ValueError("至少 1 个")
    return n


def _number(v):
    try:
        return float(str(v).replace("¥", "").replace("$", "").replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        raise ValueError(f"请填数字，「{v}」不是")


def parse_times(v) -> list[str]:
    """'09:30' / '9点,18:00' / '工作日 10:00' / '每周一 9:30' / 完整 cron -> cron 列表。"""
    s = " ".join(v) if isinstance(v, list) else str(v or "").strip()
    if re.fullmatch(r"[\d*/,\-]+( [\d*/,\-]+){4}", s):
        return [s]
    times = re.findall(r"(\d{1,2})\s*[:：点时]\s*(\d{1,2})?", s) or [(h, "") for h in re.findall(r"^(\d{1,2})$", s)]
    if not times:
        raise ValueError("没看懂时间，请写成 09:30 / 9:00,18:00 / 工作日 10:00 / 每周一 9:30")
    dow = "1-5" if "工作日" in s else (str(WEEKDAYS[m.group(1)]) if (m := re.search(r"(?:每周|周|星期)([一二三四五六日天])", s)) else "*")
    out = []
    for h, mm in times:
        h, mm = int(h), int(mm or 0)
        if h > 23 or mm > 59:
            raise ValueError(f"{h}:{mm:02d} 不是合法时间")
        out.append(f"{mm} {h} * * {dow}")
    return out


def parse_recipient(v) -> dict:
    """'财务负责人 飞书' / '投放群 企微 群' / 'ops@shop.com' / '#inventory slack' -> 接收人。"""
    s = str(v or "").strip()
    if not s:
        raise ValueError("不能为空")
    parts = [x for x in re.split(r"[\s,，/]+", s) if x]
    ch = None
    for x in parts[1:]:
        k = CHANNEL_ALIAS.get(x.lower(), x.lower())
        if k in CHANNELS:
            ch = k
    if ch is None:
        ch = "email" if "@" in parts[0] and not parts[0].startswith("@") else "slack" if parts[0].startswith("#") else None
    if ch is None:
        raise ValueError(f"请在称呼后写上渠道：{'/'.join(CHANNELS)}（或 飞书/企微/钉钉/微信/邮件）")
    kind = "group" if parts[0].startswith("#") or any(x in ("群", "group", "channel") for x in parts[1:]) else "dm"
    return {"name": parts[0], "channel": ch, "target_kind": kind}


def _metric(v):
    s = str(v or "").strip()
    if not s:
        raise ValueError("不能为空")
    try:
        k = _choice(s, METRICS)
        return k, METRICS[k].split("（")[0]
    except ValueError:
        return "custom", s  # 自由文本 = 自定义指标，名字就是消息里的称呼


def interview(answers: dict | None = None, recipients: list | None = None) -> dict:
    """交互模式约 12 问（1 接收人 + 1 平台 + 1 指标）。answers 模式读列表，旧版 *_count 键会被忽略。"""
    c = [0]
    A = answers is not None
    ask = Asker(answers, c)
    print("== 通用平台预警 配置向导 == 一次一个问题，回车用默认值，Ctrl+C 退出不写文件")

    rcs = list(recipients or [])
    if not rcs:
        if A:
            for r in answers.get("recipients") or []:
                r = parse_recipient(r) if isinstance(r, str) else {"target_kind": "dm", **r}
                rcs.append(r)
            if not rcs:
                raise SystemExit("recipients: 至少要有一个接收人")
        else:
            while True:
                rcs.append(ask("recipient", "触发后通知谁？称呼 + 渠道（群聊再加「群」）", validate=parse_recipient,
                               example="财务负责人 飞书 / 运营群 企微 群 / ops@shop.com / #inventory slack"))
                if ask("more_recipient", "再加一个接收人吗？", "n", {"y": "再加", "n": "够了"}) == "n":
                    break
    for i, r in enumerate(rcs):
        r.setdefault("target_env", f"ALERT_R{i + 1}_TARGET")
    names = [r["name"] for r in rcs]

    def pick(a, key, prompt):
        if len(names) == 1:
            return names[:]  # 只有一个接收人就不问
        def val(idx):
            out = []
            for x in idx:
                if str(x).isdigit() and 1 <= int(x) <= len(names):
                    out.append(names[int(x) - 1])
                elif x in names:
                    out.append(x)
                else:
                    raise ValueError(f"没有接收人「{x}」")
            return out
        return a(key, prompt + f"（填序号，多个用逗号：{'，'.join(f'{i + 1}={n}' for i, n in enumerate(names))}；回车=全部）",
                 ",".join(str(i + 1) for i in range(len(names))), multi=True, validate=val)

    def ask_watch(wa):
        if A:
            metric = _choice(wa.answers.get("metric", "balance"), METRICS)
            label = wa.answers.get("label") or METRICS[metric].split("（")[0]
        else:
            metric, label = wa("metric", "要盯哪个数？（填序号，或直接写名字，如「SKU-123 库存」）", "1",
                               validate=_metric, example="  ".join(f"{i}={d.split('（')[0]}" for i, d in enumerate(METRICS.values(), 1)))
        w = {"metric": metric, "label": label,
             "page_field": wa("page_field", f"「{label}」在后台哪个页面/字段？按点击顺序写", "",
                              example="推广财务 → 综合推广余额（首页那个 0 不准）")}
        rtype = wa("rule", "什么情况下提醒？", DEFAULT_RULE[metric], RULES)
        rule = {"type": rtype}
        if rtype != "zero_or_missing":
            rule["threshold"] = wa("threshold", f"阈值？（{THRESHOLD_HINT.get(rtype, '数值')}）",
                                   4 if rtype == "days_left" else None, validate=_number)
        if rtype == "change_pct":
            rule["direction"] = wa("direction", "看涨还是看跌？", "down", {"up": "只看上涨", "down": "只看下降", "any": "都看"}) \
                if A else "down" if (rule["threshold"] >= 0) else "up"
            if not A:
                rule["threshold"] = abs(rule["threshold"])  # 交互：正数=看下降，负数=看上涨（少问一题）
        w["rule"] = rule
        w["recipients"] = pick(wa, "recipients", "这个数触发后通知谁？")
        tpl = wa("template", "提醒话术？可用 {platform} {metric} {value} {threshold} {days} {pct}；回车用默认",
                 DEFAULT_TPL.get(rtype, ""))
        ok = wa.answers.get("ok_template", DEFAULT_TPL.get(f"ok_{rtype}", "")) if A else DEFAULT_TPL.get(f"ok_{rtype}", "")
        w["templates"] = {k: v for k, v in ((rtype, tpl), ("ok", ok)) if v}
        return w

    def new_platform(pa):
        name = pa("name", "要监控哪个平台？（消息里就显示这个名字）", "平台1" if A else None, validate=_req,
                  example="大众点评 / 高德 / Shopify")
        p = {"name": name, "url": pa.answers.get("url", "") if A else "",
             "login_account": pa("login_account", f"「{name}」用哪个账号登录？（只写别名或谁扫码，不要写密码）", ""),
             "login_steps": [], "account_switch_steps": [], "watches": []}
        if A:
            for k in ("login_steps", "account_switch_steps"):
                v = pa.answers.get(k) or []
                p[k] = [x.strip() for x in re.split(r"[,，、]+", v) if x.strip()] if isinstance(v, str) else v
        return p

    platforms = []
    if A:
        for pans in answers.get("platforms") or [{}]:
            p = new_platform(Asker(pans, c))
            for wans in pans.get("watches") or [{}]:
                p["watches"].append(ask_watch(Asker(wans, c)))
            platforms.append(p)
    else:
        p = new_platform(ask)
        while True:
            p["watches"].append(ask_watch(ask))
            more = ask("more", "还要再加吗？", "n", {"n": "完成", "m": f"「{p['name']}」再盯一个数", "p": "加一个新平台"})
            if more == "n":
                break
            if more == "p":
                platforms.append(p)
                p = new_platform(ask)
        platforms.append(p)

    cfg: dict = {"timezone": "Asia/Shanghai", "recipients": rcs, "platforms": platforms}
    cfg["schedules"] = [{"cron": x} for x in ask("check_time", "每天几点检查？", "10:00", validate=parse_times,
                                                example="09:30 / 9:00,18:00 / 工作日 10:00 / 每周一 9:30")]
    cfg["send_when_not_triggered"] = (answers.get("send_when_not_triggered", "n") in ("y", True)) if A else False
    cfg["login_expired_recipients"] = pick(ask, "login_expired_recipients", "登录失效/读不到数时提醒谁去登录？")
    if A:
        cfg["timezone"] = answers.get("timezone", cfg["timezone"])
    elif ask("advanced", "要改高级设置吗？（时区、后台网址、登录步骤、子账户切换、没触发也发、正常话术）", "n",
             {"n": "跳过（推荐）", "y": "设置"}) == "y":
        cfg["timezone"] = ask("timezone", "时区？", "Asia/Shanghai")
        for p in platforms:
            p["url"] = ask("url", f"「{p['name']}」后台网址？（可留空）", "")
            p["login_steps"] = ask("login_steps", f"「{p['name']}」登录步骤？（逗号分隔，可留空）", "", multi=True) or []
            p["account_switch_steps"] = ask("account_switch_steps", f"「{p['name']}」登录后切子账户的点击步骤？（逗号分隔，不需要留空）", "", multi=True) or []
        cfg["send_when_not_triggered"] = ask("send_when_not_triggered", "没触发时也发一条“一切正常”吗？", "n", {"y": "发", "n": "不发"}) == "y"
        for p in platforms:
            for w in p["watches"]:
                ok = ask("ok_template", f"「{p['name']}·{w['label']}」正常时的话术？（回车用默认）", w["templates"].get("ok", "{platform}·{metric}{value}，正常。"))
                w["templates"]["ok"] = ok
    cfg["default_recipients"] = names[:1]
    return cfg


def _req(v):
    if v is None or not str(v).strip():
        raise ValueError("不能为空")
    return str(v).strip()


def summary(cfg: dict) -> str:
    lines = ["✔ 配置已生成，请核对："]
    for p in cfg["platforms"]:
        for w in p["watches"]:
            r = w["rule"]
            th = f" {r['threshold']:g}" if "threshold" in r else ""
            lines.append(f"  · {p['name']} / {w['label']}：{RULES[r['type']].split('（')[0]}{th} → {'、'.join(w['recipients'])}")
    lines.append(f"  · 检查时间（cron）：{', '.join(s['cron'] for s in cfg['schedules'])}；登录失效提醒：{'、'.join(cfg['login_expired_recipients'])}")
    envs = [f"{r['name']}={r.get('target_env', '?')}" for r in cfg["recipients"]]
    lines.append(f"  下一步：在环境变量里填好接收人 ID/Webhook（{'；'.join(envs)}），"
                 f"然后 python modules/platform-alert/evaluate.py 配置.yaml 读数.json 试跑（只计算不发送）。")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--answers")
    ap.add_argument("--out", default="platform-alert.yaml")
    a = ap.parse_args(argv)
    ans = yaml.safe_load(open(a.answers, encoding="utf-8")) if a.answers else None
    try:
        cfg = interview(ans)
    except (KeyboardInterrupt, EOFError):
        print("\n已取消，没有写入文件。")
        return 1
    Path(a.out).write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"已生成 {a.out}\n" + summary(cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
