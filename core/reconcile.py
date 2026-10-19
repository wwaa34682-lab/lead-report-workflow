"""Reconciliation rules. All gaps are one-sided: gap = max(source - crm, 0).

A positive gap means the platform shows more than staff recorded -> red.
Over-filling (crm > source) is never a negative gap; it is surfaced as a note.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

DASH = "—"


@dataclass
class Table:
    title: str
    headers: list[str]
    rows: list[list]
    red_cells: set = field(default_factory=set)       # (row, col)
    header_color: str = "#2D6EB4"
    footnotes: list[str] = field(default_factory=list)
    name: str = "table"


def gap(source, crm):
    if source in (None, DASH) or crm in (None, DASH):
        return DASH
    return max(int(source) - int(crm), 0)


def fill_gap_table(title, group_label, groups, lead_cols, leads, filled, *, missing_cols=(),
                   incomplete=None, header_color="#E67828", total_row=False, name="fill") -> Table:
    """groups: [(gid, display)], lead_cols: [(kind_or_list, label)], leads: gid -> Counter(kind)."""
    headers = [group_label] + [lbl for _, lbl in lead_cols] + ["已填数", "未填数"]
    rows, red, notes = [], set(), []
    tot = [0] * (len(lead_cols) + 2)
    for ri, (gid, disp) in enumerate(groups):
        vals = []
        for kinds, lbl in lead_cols:
            if lbl in missing_cols:
                vals.append(DASH)
                continue
            ks = [kinds] if isinstance(kinds, str) else kinds
            c = leads.get(gid, {})
            vals.append(sum(c.values()) if "*" in ks else sum(c.get(k, 0) for k in ks))
        nums = [v for v in vals if v != DASH]
        src_total = sum(nums) if nums else DASH
        f = filled.get(gid, 0)
        g = gap(src_total, f)
        if g != DASH and len(nums) < len(vals):
            g = f"{g}*"
            notes.append("* 部分来源未取到数据，未填数仅按已取到的来源计算")
        row = [disp, *vals, f, g]
        if str(g).rstrip("*") not in (DASH, "0"):
            red.add((ri, len(row) - 1))
        if src_total != DASH and int(f) > int(src_total):
            notes.append(f"{disp}: 已填({f}) > 平台数({src_total})，请核对是否跨日/跨渠道录入")
        if incomplete and incomplete.get(gid):
            notes.append(f"{disp}: {incomplete[gid]} 条记录缺必填字段，未计入已填")
        for i, v in enumerate(row[1:]):
            try:
                tot[i] += int(str(v).rstrip("*"))
            except ValueError:
                pass
        rows.append(row)
    if total_row:
        rows.append(["合计", *tot])
        if tot[-1] > 0:
            red.add((len(rows) - 1, len(headers) - 1))
    return Table(title, headers, rows, red, header_color, sorted(set(notes)), name)


def verification_vs_visit(label, group_label, groups, ver_by_day, vis_by_day, days: list[date],
                          ver_name="核销", vis_name="到店", header_color="#2D6EB4") -> list[Table]:
    """Three views: by group, by day, full day x group matrix (both cells red where gap>0)."""
    gids = [g for g, _ in groups]
    ver_tot = {g: sum(ver_by_day[d].get(g, 0) for d in days) for g in gids}
    vis_tot = {g: sum(vis_by_day[d].get(g, 0) for d in days) for g in gids}

    rows, red, tg = [], set(), 0
    for ri, (g, disp) in enumerate(groups):
        x = gap(ver_tot[g], vis_tot[g]); tg += x
        rows.append([disp, ver_tot[g], vis_tot[g], x])
        if x > 0:
            red.add((ri, 3))
    rows.append(["合计", sum(ver_tot.values()), sum(vis_tot.values()), tg])
    if tg:
        red.add((len(rows) - 1, 3))
    t1 = Table(f"{label} {ver_name} vs {vis_name}（按分组）", [group_label, ver_name, vis_name, "差额"], rows, red,
               header_color, name="reconcile-by-group")

    rows, red = [], set()
    for ri, d in enumerate(days):
        dg = sum(gap(ver_by_day[d].get(g, 0), vis_by_day[d].get(g, 0)) for g in gids)
        rows.append([f"{d.month}/{d.day}", sum(ver_by_day[d].values()), sum(vis_by_day[d].values()), dg])
        if dg:
            red.add((ri, 3))
    rows.append(["合计", sum(ver_tot.values()), sum(vis_tot.values()), tg])
    if tg:
        red.add((len(rows) - 1, 3))
    t2 = Table(f"{label} {ver_name} vs {vis_name}（按日）", ["日期", ver_name, vis_name, "差额"], rows, red,
               header_color, ["差额 = Σ各分组 max(核销−到店, 0)，不同分组之间不互相抵消"], name="reconcile-by-day")

    headers = ["日期"]
    for _, disp in groups:
        headers += [f"{disp}{ver_name[:1]}", f"{disp}{vis_name[:1]}"]
    headers.append("日差额")
    rows, red = [], set()
    for ri, d in enumerate([*days, None]):
        row = [f"{d.month}/{d.day}" if d else "合计"]
        dg = 0
        for gi, g in enumerate(gids):
            a = ver_by_day[d].get(g, 0) if d else ver_tot[g]
            b = vis_by_day[d].get(g, 0) if d else vis_tot[g]
            x = gap(a, b); dg += x
            row += [a, b]
            if x > 0:
                red |= {(ri, 1 + 2 * gi), (ri, 2 + 2 * gi)}
        row.append(dg)
        if dg:
            red.add((ri, len(headers) - 1))
        rows.append(row)
    t3 = Table(f"{label} {ver_name} vs {vis_name}（日×分组矩阵）", headers, rows, red, header_color,
               [f"红色 = 当日该分组 {ver_name} > {vis_name}，两格同时标红"], name="reconcile-matrix")
    return [t1, t2, t3]


def fmt_duration(sec) -> str:
    if sec in (None, ""):
        return DASH
    sec = int(round(float(sec)))
    if sec < 60:
        return f"{sec}秒"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m}分{s}秒" if s else f"{m}分"
    h, m = divmod(m, 60)
    return f"{h}小时{m}分"


def response_time_table(title, group_label, rows_in, threshold_sec=None, header_color="#E67828") -> Table:
    """rows_in: [(group_display, agent, avg_seconds, consults)]"""
    rows, red = [], set()
    for ri, (g, agent, avg, n) in enumerate(rows_in):
        rows.append([g, agent or DASH, fmt_duration(avg), DASH if n in (None, "") else n])
        if threshold_sec and avg not in (None, "") and float(avg) > threshold_sec:
            red.add((ri, 2))
    notes = [f"红色 = 平均响应时长超过 {fmt_duration(threshold_sec)}"] if threshold_sec else []
    return Table(title, [group_label, "客服", "平均响应时长", "咨询人数"], rows, red, header_color, notes,
                 name="response-time")
