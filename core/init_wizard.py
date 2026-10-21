"""`python run.py init` — interview the user and write config.yaml + .env.example.

Same question flow as docs/agent-onboarding.md (the AI agent asks these in chat when no config
exists, then calls `python run.py init --answers answers.yaml`). Every question has a key; in
--answers mode the value is taken from the file, otherwise asked on the terminal.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

CHANNELS = {
    "feishu": ("飞书 / Lark（应用机器人）", {"app_id_env": "FEISHU_APP_ID", "app_secret_env": "FEISHU_APP_SECRET"}, "receive_id_env"),
    "wecom_bot": ("企业微信群机器人", {}, "webhook_env"),
    "dingtalk": ("钉钉群机器人", {}, "webhook_env"),
    "wechat": ("个人微信（由 AI 助手/人工代发）", {}, None),
    "slack": ("Slack", {"token_env": "SLACK_BOT_TOKEN"}, "channel_env"),
    "teams": ("Microsoft Teams", {}, "webhook_env"),
    "telegram": ("Telegram", {"token_env": "TELEGRAM_BOT_TOKEN"}, "chat_id_env"),
    "email": ("Email (SMTP)", {"host_env": "SMTP_HOST", "port_env": "SMTP_PORT", "user_env": "SMTP_USER",
                               "password_env": "SMTP_PASSWORD"}, "to_env"),
    "webhook": ("通用 Webhook", {}, "url_env"),
}
INGEST = {"api": "官方 API", "csv": "导出文件（CSV/Excel/JSON）", "browser-manual": "浏览器辅助人工读数", "webhook": "平台推送 Webhook"}
TEMPLATES = {"local-life-chain": "本地生活连锁门店", "ecommerce": "电商 / 店铺客服", "education": "教育培训 / 课程顾问", "blank": "空白"}


class Asker:
    def __init__(self, answers: dict | None):
        self.answers = answers

    def __call__(self, key, prompt, default=None, choices=None, multi=False):
        if self.answers is not None:
            v = self.answers.get(key, default)
        else:
            hint = ""
            if choices:
                hint = "\n" + "\n".join(f"    {k} = {v}" for k, v in choices.items()) + "\n"
            raw = input(f"{prompt}{hint}  [{default if default is not None else ''}] > ").strip()
            v = raw or default
        if multi and isinstance(v, str):
            v = [x.strip() for x in re.split(r"[,，、\s]+", v) if x.strip()]
        if choices and not multi and v not in choices:
            raise SystemExit(f"{key}: {v!r} 不在可选项 {list(choices)} 中")
        return v


def slug(s: str, i: int) -> str:
    a = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return a or f"g{i + 1}"


def run(out: Path, answers_file: Path | None = None, templates_dir: Path | None = None) -> Path:
    answers = yaml.safe_load(answers_file.read_text(encoding="utf-8")) if answers_file else None
    ask = Asker(answers)
    print("== 客资对账工作流 配置向导 ==（回车用默认值）")
    tpl = ask("template", "1/9 选一个行业模板作为起点", "blank", TEMPLATES)
    cfg: dict = {}
    if tpl != "blank" and templates_dir and (templates_dir / f"{tpl}.yaml").exists():
        cfg = yaml.safe_load((templates_dir / f"{tpl}.yaml").read_text(encoding="utf-8"))
    cfg["timezone"] = ask("timezone", "2/9 时区", cfg.get("timezone", "Asia/Shanghai"))

    # groups
    stores = ask("stores", "3/9 门店/团队名称（逗号分隔，没有就留空）", "", multi=True) or []
    people = ask("people", "    负责人/员工名称（按人统计的平台用，逗号分隔，可留空）", "", multi=True) or []
    groups = {}
    if stores:
        groups["stores"] = [{"id": f"s{i + 1}", "name": n, "aliases": []} for i, n in enumerate(stores)]
    if people:
        groups["people"] = [{"id": f"p{i + 1}", "name": n, "aliases": []} for i, n in enumerate(people)]
    if groups:
        cfg["groups"] = groups

    # CRM
    crm_type = ask("crm_type", "4/9 客户记录（CRM）从哪里读", "crm-csv",
                   {"crm-csv": "CRM/表格导出文件", "crm-sql": "数据库只读视图", "custom": "自写适配器（Salesforce/HubSpot/多维表格 API…）"})
    crm = {"id": "crm", "name": ask("crm_name", "    CRM 名称（展示用）", "CRM"), "type": crm_type, "role": "crm"}
    if crm_type == "crm-csv":
        crm["path"] = ask("crm_path", "    导出文件路径（可含 {date}）", "exports/crm_{date}.csv")
        crm["max_age_minutes"] = 120
    elif crm_type == "crm-sql":
        crm["dsn_env"] = "CRM_DSN"
        crm["query"] = ask("crm_query", "    只读 SQL（用 :start :end）", "select * from v_leads where first_contact_date between :start and :end")
    else:
        crm["class"] = ask("crm_class", "    适配器类 package.module:Class", "my_adapters.crm:MyCrmAdapter")
    cols = {}
    for k, prompt, d in [("channel", "渠道列名", "获客渠道"), ("store", "门店列名", "门店"), ("owner", "创建人/负责人列名", "创建人"),
                         ("first_contact", "首次咨询时间列名", "首次咨询时间"), ("created", "创建时间列名", "创建时间"),
                         ("visit", "到店/到访时间列名（没有就留空）", "到店时间"), ("contact", "联系方式列名（手机号/平台ID，用于逐条匹配，可留空）", "手机号")]:
        cols[k] = ask(f"crm_col_{k}", f"    {prompt}", d)
    crm["field_map"] = {"channel": cols["channel"], "contact": cols["contact"] or None}
    crm["group_fields"] = {k: v for k, v in (("stores", cols["store"]), ("people", cols["owner"])) if v}
    crm["time_fields"] = {k: cols[k] for k in ("first_contact", "created", "visit") if cols[k]}
    crm["field_map"] = {k: v for k, v in crm["field_map"].items() if v}

    # sources
    sources, reports = [crm], []
    n = int(ask("source_count", "5/9 要接入几个线索来源平台", 1))
    for i in range(n):
        a = (answers or {}).get("sources", [{}] * n)[i] if answers else None
        sa = Asker(a) if answers else ask
        name = sa("name", f"  来源{i + 1} 名称（如 某点评平台 / 某社媒 / 某地图 / 官网表单）", f"平台{i + 1}")
        sid = sa("id", "    英文 id", slug(name, i) if slug(name, i) != f"g{i + 1}" else f"src{i + 1}")
        how = sa("ingest", "    接入方式", "browser-manual", INGEST)
        gb = sa("group_by", "    按什么分组统计", "stores" if stores else "people", {k: k for k in groups} or {"stores": "stores"})
        kinds = sa("kinds", "    客资类型拆列（如 电话数,后台咨询数；只有一个数就填 客资数）", "客资数", multi=True)
        chans = sa("crm_channels", f"    CRM『{cols['channel']}』里对应的取值（精确匹配，可多个）", name, multi=True)
        s = {"id": sid, "name": name, "type": how, "role": "leads", "group_by": gb}
        if how == "api":
            s.update(url=f"https://api.example.com/{sid}/leads", headers={"Authorization": "Bearer ${" + sid.upper() + "_TOKEN}"},
                     records_path="data.items", field_map={"group": "store_name", "time": "created_at", "kind": "type", "contact": "phone"})
        elif how in ("csv", "webhook"):
            s.update(path=f"exports/{sid}_{{date}}.{'jsonl' if how == 'webhook' else 'csv'}", max_age_minutes=120 if how == "csv" else None,
                     field_map={"group": "store", "time": "time", "kind": "type", "contact": "phone"})
        else:
            s.update(capture_dir=f"captures/{sid}", max_age_minutes=90)
        sources.append(s)
        # "phone:电话数,chat:后台咨询数" -> kind id + label; without ":" the label doubles as the kind id
        pairs = [k.split(":", 1) if ":" in k else [k, k] for k in kinds]
        kind_ids = [p_[0] for p_ in pairs] if len(pairs) > 1 else ["*"]
        kinds = [p_[1] for p_ in pairs]
        reports.append({"id": f"fill_{sid}", "type": "fill_gap", "source": sid, "crm_source": "crm", "crm_channels": chans,
                        "group_by": gb, "group_label": "门店" if gb == "stores" else "负责人",
                        "title": "{date_label} " + name + " 客资填写情况",
                        "columns": [{"kinds": [k], "label": lbl} for k, lbl in zip(kind_ids, kinds)],
                        "record_match": False})
    if cols["visit"] and stores and ask("want_reconcile", "    是否做『核销/验券 vs 到店』对账（y/n）", "n") == "y":
        vname = ask("verification_name", "    核销数据来源平台名称", "团购平台")
        sources.append({"id": "verification", "name": vname, "type": "csv", "role": "verification", "group_by": "stores",
                        "path": "exports/verification_{month}.csv", "max_age_minutes": 120, "field_map": {"group": "store", "time": "verified_at"}})
        reports.append({"id": "reconcile_visits", "type": "verification_vs_visit", "verification_source": "verification",
                        "crm_source": "crm", "group_by": "stores", "group_label": "门店", "visit_time_field": "visit",
                        "verification_label": "核销", "visit_label": "到店"})
    cfg["sources"], cfg["reports"] = sources, reports

    # metrics
    cfg["metrics"] = {
        **(cfg.get("metrics") or {}),
        "date_attribution": ask("date_attribution", "6/9 客资按哪个时间归属到某天", "first_contact",
                                {"first_contact": "首次咨询时间", "created": "CRM 创建时间"}),
        "day_window": {"start": ask("day_start", "    每天从几点切日（HH:MM）", "00:00")},
        "dedupe": {"scope": ask("dedupe", "    同一联系方式同一天重复咨询", "day", {"day": "当天只算一次", "none": "不去重"})},
        "required_fields": ask("required_fields", "    CRM 必填字段（缺了不算已填，逗号分隔）", "channel,group", multi=True),
        "valid_lead": (cfg.get("metrics") or {}).get("valid_lead") or {"filters": []},
        "on_source_failure": ask("on_failure", "    某平台取数失败时", "hold", {"hold": "相关报表暂停发送并告警", "send_with_dash": "照发，缺的数显示 —"}),
    }

    # schedules
    m = ask("morning_time", "7/9 早报时间（复核昨天，HH:MM，留空=不要早报）", "09:00")
    e = ask("evening_time", "    晚报时间（统计今天，HH:MM，留空=不要晚报）", "21:00")
    all_ids = [r["id"] for r in reports]
    cfg["schedules"] = {}
    if m:
        cfg["schedules"]["morning"] = {"cron": f"{int(m[3:5])} {int(m[:2])} * * *", "data_day": "yesterday",
                                       "reports": all_ids, "caption": "客资填写复核（昨日）"}
    if e:
        cfg["schedules"]["evening"] = {"cron": f"{int(e[3:5])} {int(e[:2])} * * *", "data_day": "today",
                                       "reports": [r for r in all_ids if r.startswith("fill_")], "caption": "客资填写情况（今日）"}

    # recipients — per-recipient channel / target / reports / format / evidence
    rcs = []
    k = int(ask("recipient_count", "8/9 有几位接收人（个人或群）", 1))
    for i in range(k):
        a = (answers or {}).get("recipients", [{}] * k)[i] if answers else None
        ra = Asker(a) if answers else ask
        name = ra("name", f"  接收人{i + 1} 称呼（如 运营负责人 / 门店群）", f"接收人{i + 1}")
        ctype = ra("channel", "    在哪个平台接收", "feishu", {c: v[0] for c, v in CHANNELS.items()})
        kind = ra("target_kind", "    私聊还是群", "dm", {"dm": "私聊", "group": "群"})
        wants = ra("reports", f"    接收哪些（{','.join(cfg['schedules'])},alerts）", ",".join([*cfg["schedules"], "alerts"]), multi=True)
        fmt = ra("format", "    格式", "image", {"image": "只发图片", "image+text": "图片+文字说明", "file": "文件附件"})
        ev = ra("evidence", "    数字对不上时附证据截图（y/n）", "y") in ("y", True, "yes")
        label, fixed, target_key = CHANNELS[ctype]
        envp = f"{ctype.upper()}_{('R' + str(i + 1))}"
        ch = {"type": ctype, **fixed}
        if target_key:
            ch[target_key] = f"{envp}_{'TARGET' if target_key not in ('webhook_env', 'url_env') else 'WEBHOOK'}"
        if ctype == "feishu":
            ch["receive_id_type"] = "open_id" if kind == "dm" else "chat_id"
        if ctype in ("dingtalk", "teams"):
            ch["image_base_url"] = "https://static.example.com/lead-reports"
        rcs.append({"id": f"r{i + 1}", "name": name, "target_kind": kind, "channel": ch, "reports": wants,
                    "format": fmt, "evidence": ev})
    if not any("alerts" in r["reports"] for r in rcs) and rcs:
        who = ask("alert_recipient", "9/9 平台登录失效/取数失败时，提醒谁（填接收人序号）", "1")
        rcs[int(who) - 1]["reports"].append("alerts")
    cfg["recipients"] = rcs

    # optional module: platform-alert（通用平台预警，见 modules/platform-alert）
    if ask("want_platform_alert", "附加 是否开启『通用平台预警』（余额/花费/评分/差评/库存…任意指标，y/n）", "n") == "y":
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "platform_alert_wizard", Path(__file__).resolve().parents[1] / "modules/platform-alert/wizard.py")
        pw = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pw)
        pa_recipients = [{"name": r["name"], "channel": r["channel"].get("type", "feishu"), "target_kind": r.get("target_kind", "dm")}
                         for r in rcs]
        pa_cfg = pw.interview((answers or {}).get("platform_alert") if answers is not None else None, recipients=pa_recipients)
        out.parent.mkdir(parents=True, exist_ok=True)
        (out.parent / "platform-alert.yaml").write_text(
            yaml.safe_dump(pa_cfg, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
        cfg["platform_alert"] = {"config": "platform-alert.yaml"}
    cfg.setdefault("outputs", {"dir": "runs", "dpi": 160, "font": {"family": "Noto Sans CJK SC"}})

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    envs = sorted({v for r in rcs for kk, v in r["channel"].items() if kk.endswith("_env")} |
                  {m_.group(1) for m_ in re.finditer(r"\$\{([A-Z0-9_]+)", out.read_text(encoding="utf-8"))})
    (out.parent / ".env.example").write_text("# 填好后另存为 .env（已在 .gitignore 中），不要提交\n" + "".join(f"{e}=\n" for e in envs), encoding="utf-8")
    print(f"已生成 {out} 和 {out.parent / '.env.example'}；下一步：python run.py validate --config {out}")
    return out
