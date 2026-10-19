"""Thorough config validation with human-readable messages (zh + field path)."""
from __future__ import annotations

import os
from pathlib import Path

SOURCE_TYPES = {"csv", "file", "api", "http-json", "browser-manual", "webhook", "crm-csv", "crm-sql", "custom"}
ROLES = {"leads", "crm", "verification", "response_time"}
REPORT_TYPES = {"fill_gap": ("source", "crm_source", "crm_channels", "group_by"),
                "verification_vs_visit": ("verification_source", "crm_source", "group_by"),
                "response_time": ("source", "group_by")}
CHANNEL_ENV = {
    "feishu": ["app_id_env", "app_secret_env", "receive_id_env"], "lark": ["app_id_env", "app_secret_env", "receive_id_env"],
    "wecom_bot": ["webhook_env"], "dingtalk": ["webhook_env"], "slack": ["token_env", "channel_env"],
    "teams": ["webhook_env"], "telegram": ["token_env", "chat_id_env"],
    "email": ["host_env", "user_env", "password_env", "to_env"], "webhook": ["url_env"],
    "wechat": [], "agent_outbox": [], "custom": [],
}
FORMATS = {"image", "image+text", "file"}


def check(cfg: dict, check_env: bool = False) -> tuple[list[str], list[str]]:
    E, W = [], []
    if not cfg.get("timezone"):
        W.append("timezone 未设置，默认 UTC —— 日期归属会按 UTC 切日，通常应设为 Asia/Shanghai 等")
    groups = cfg.get("groups") or {}
    if not groups:
        E.append("groups: 至少定义一个分组集合（如 stores / people），每个成员需 id + name")
    for gs, members in groups.items():
        ids = [m.get("id") for m in members or []]
        if any(not m.get("id") or not m.get("name") for m in members or []):
            E.append(f"groups.{gs}: 每个成员都需要 id 和 name")
        if len(ids) != len(set(ids)):
            E.append(f"groups.{gs}: id 重复")
        seen = {}
        for m in members or []:
            for a in [m.get("name"), *(m.get("aliases") or [])]:
                if a in seen and seen[a] != m.get("id"):
                    E.append(f"groups.{gs}: 名称/别名 {a!r} 同时属于 {seen[a]} 和 {m.get('id')}，会导致匹配歧义")
                seen[a] = m.get("id")
    srcs = {}
    for i, s in enumerate(cfg.get("sources") or []):
        p = f"sources[{i}]({s.get('id', '?')})"
        for k in ("id", "type", "role"):
            if not s.get(k):
                E.append(f"{p}.{k}: 必填")
        if s.get("type") and s["type"] not in SOURCE_TYPES:
            E.append(f"{p}.type: {s['type']!r} 不支持，可选 {sorted(SOURCE_TYPES)}")
        if s.get("role") and s["role"] not in ROLES:
            E.append(f"{p}.role: {s['role']!r} 不支持，可选 {sorted(ROLES)}")
        if s.get("type") in ("csv", "file", "webhook", "crm-csv") and not s.get("path"):
            E.append(f"{p}.path: 文件类来源需要 path")
        if s.get("type") in ("api", "http-json") and not s.get("url"):
            E.append(f"{p}.url: API 来源需要 url")
        if s.get("type") == "custom" and ":" not in str(s.get("class", "")):
            E.append(f"{p}.class: 自定义适配器写成 'package.module:ClassName'")
        if s.get("group_by") and s["group_by"] not in groups:
            E.append(f"{p}.group_by: 分组集合 {s['group_by']!r} 未在 groups 中定义")
        if s.get("type") in ("browser-manual", "csv", "crm-csv") and s.get("max_age_minutes") is None:
            W.append(f"{p}: 未设 max_age_minutes —— 无法强制『每次实时重拉』，可能误用旧数据")
        raw = (cfg.get("_raw_sources") or [{}] * (i + 1))[i] if i < len(cfg.get("_raw_sources") or []) else s
        for h, v in (raw.get("headers") or {}).items():
            if v and "${" not in str(v) and any(t in h.lower() for t in ("auth", "token", "key", "cookie")):
                E.append(f"{p}.headers.{h}: 疑似明文密钥，请改为 ${{ENV_VAR}}")
        if s.get("id") in srcs:
            E.append(f"{p}.id: 重复")
        srcs[s.get("id")] = s
    reports = {}
    for i, r in enumerate(cfg.get("reports") or []):
        p = f"reports[{i}]({r.get('id', '?')})"
        t = r.get("type")
        if t not in REPORT_TYPES:
            E.append(f"{p}.type: 可选 {sorted(REPORT_TYPES)}")
            continue
        for k in REPORT_TYPES[t]:
            if not r.get(k):
                E.append(f"{p}.{k}: {t} 报表必填")
        for k in ("source", "crm_source", "verification_source"):
            if r.get(k) and r[k] not in srcs:
                E.append(f"{p}.{k}: 来源 {r[k]!r} 未在 sources 中定义")
        if r.get("crm_source") in srcs and srcs[r["crm_source"]].get("role") != "crm":
            E.append(f"{p}.crm_source: {r['crm_source']} 的 role 应为 crm")
        if r.get("group_by") and r["group_by"] not in groups:
            E.append(f"{p}.group_by: {r['group_by']!r} 未定义")
        reports[r.get("id")] = r
    scheds = cfg.get("schedules") or {}
    if not scheds:
        E.append("schedules: 至少定义一个时段（如 morning / evening）")
    for name, sc in scheds.items():
        if name == "alerts":
            E.append("schedules.alerts: 'alerts' 是保留字（告警订阅），换个时段名")
        for rid in sc.get("reports") or []:
            if rid not in reports:
                E.append(f"schedules.{name}.reports: 报表 {rid!r} 未定义")
        if sc.get("data_day", "yesterday") not in ("today", "yesterday") and len(str(sc.get("data_day"))) != 10:
            E.append(f"schedules.{name}.data_day: today | yesterday | YYYY-MM-DD")
    rcs = cfg.get("recipients") or []
    if not rcs:
        W.append("recipients: 没有接收人 —— 报表只会生成不会发送")
    if rcs and not any("alerts" in (r.get("reports") or []) for r in rcs):
        W.append("recipients: 没有人订阅 alerts —— 平台登录失效时没人会收到提醒")
    for i, rc in enumerate(rcs):
        p = f"recipients[{i}]({rc.get('id', '?')})"
        ch = rc.get("channel") or {}
        if not rc.get("id"):
            E.append(f"{p}.id: 必填")
        if ch.get("type") not in CHANNEL_ENV:
            E.append(f"{p}.channel.type: {ch.get('type')!r} 不支持，可选 {sorted(CHANNEL_ENV)}")
            continue
        for k in CHANNEL_ENV[ch["type"]]:
            if not ch.get(k):
                E.append(f"{p}.channel.{k}: {ch['type']} 需要该环境变量名")
            elif check_env and not os.environ.get(ch[k]):
                E.append(f"{p}.channel.{k}: 环境变量 {ch[k]} 未设置")
        for k, v in ch.items():
            if k.endswith("_env") and v and not str(v).replace("_", "").isalnum():
                E.append(f"{p}.channel.{k}: 应填环境变量『名』，不是值本身")
            if k in ("webhook", "url", "token", "secret") and v:
                E.append(f"{p}.channel.{k}: 不要把密钥/带 token 的 URL 写进配置，改用 {k}_env")
        if rc.get("format", "image") not in FORMATS:
            E.append(f"{p}.format: 可选 {sorted(FORMATS)}")
        if ch["type"] in ("dingtalk", "teams") and not (ch.get("image_base_url") or ch.get("inline_data_uri")):
            W.append(f"{p}: {ch['type']} 机器人不能直接上传图片，需 image_base_url（图片托管地址）")
        for w in rc.get("reports") or []:
            if w != "alerts" and w not in scheds:
                E.append(f"{p}.reports: {w!r} 既不是时段名也不是 alerts")
        for rid in rc.get("report_ids") or []:
            if rid not in reports:
                E.append(f"{p}.report_ids: {rid!r} 未定义")
    font = (cfg.get("outputs") or {}).get("font") or {}
    if font.get("path") and not Path(font["path"]).exists():
        E.append(f"outputs.font.path: 字体文件不存在 {font['path']}")
    return E, W
