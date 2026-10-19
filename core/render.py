"""Render `Table`s to PNG with matplotlib. CJK font is configurable.

outputs.font:
  family: "Noto Sans CJK SC"      # any installed family (fc-list :lang=zh)
  path: null                      # optional .ttf/.otf/.ttc to register first
  fallback: ["Microsoft YaHei", "PingFang SC", "Source Han Sans SC", "WenQuanYi Zen Hei"]
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager as fm  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from matplotlib.textpath import TextPath  # noqa: E402

from .reconcile import Table  # noqa: E402

RED = "#DC143C"


class Renderer:
    def __init__(self, out_cfg: dict | None = None):
        out_cfg = out_cfg or {}
        font = out_cfg.get("font") or {}
        if font.get("path"):
            fm.fontManager.addfont(font["path"])
        installed = {f.name for f in fm.fontManager.ttflist}
        wanted = [font.get("family", "Noto Sans CJK SC"), *(font.get("fallback") or [
            "Source Han Sans SC", "PingFang SC", "Microsoft YaHei", "WenQuanYi Zen Hei", "SimHei"])]
        self.family = next((f for f in wanted if f in installed), None)
        if self.family is None:
            raise RuntimeError(f"no CJK font found (tried {wanted}); install Noto Sans CJK SC or set outputs.font")
        self.dpi = int(out_cfg.get("dpi", 160))
        self.sizes = {"title": 15, "header": 11.5, "cell": 11, "note": 9}
        self.sizes.update(out_cfg.get("font_sizes") or {})

    def _fp(self, bold=False):
        return fm.FontProperties(family=self.family, weight="bold" if bold else "normal")

    def _w(self, text, size, bold=False) -> float:
        return TextPath((0, 0), str(text), size=size, prop=self._fp(bold)).get_extents().width

    def render(self, t: Table, out: Path) -> Path:
        S = self.sizes
        px, py = 9.0, 6.0
        col_w = []
        for i, h in enumerate(t.headers):
            w = self._w(h, S["header"], True)
            for r in t.rows:
                w = max(w, self._w(r[i], S["cell"]))
            col_w.append(max(w + 2 * px, 34))
        need = self._w(t.title, S["title"], True) + 30
        if sum(col_w) < need:
            extra = (need - sum(col_w)) / len(col_w)
            col_w = [c + extra for c in col_w]
        title_h, head_h, row_h, note_h = S["title"] + 2.4 * py, S["header"] + 2 * py, S["cell"] + 2 * py, S["note"] * 1.6
        m = 12.0
        W = sum(col_w) + 2 * m
        notes_w = max([self._w(n, S["note"]) for n in t.footnotes] or [0]) + 2 * m
        W = max(W, notes_w)
        H = 2 * m + title_h + head_h + row_h * len(t.rows) + (note_h * len(t.footnotes) + 4 if t.footnotes else 0)

        fig = plt.figure(figsize=(W / 72, H / 72), dpi=self.dpi)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
        tw = sum(col_w)

        def cell(x, y, w, h, text, size, bold=False, color="black", bg=None):
            ax.add_patch(Rectangle((x, y), w, h, facecolor=bg or "none", edgecolor="black", linewidth=0.6))
            ax.text(x + w / 2, y + h / 2, str(text), ha="center", va="center_baseline", fontsize=size,
                    fontproperties=self._fp(bold), color=color)

        y = m
        ax.add_patch(Rectangle((m, y), tw, title_h, facecolor=t.header_color, edgecolor="none"))
        ax.text(m + tw / 2, y + title_h / 2, t.title, ha="center", va="center_baseline", color="white",
                fontsize=S["title"], fontproperties=self._fp(True))
        y += title_h
        x = m
        for i, h in enumerate(t.headers):
            cell(x, y, col_w[i], head_h, h, S["header"], True, bg="#F5F5F5"); x += col_w[i]
        y += head_h
        for ri, r in enumerate(t.rows):
            x = m
            bold = str(r[0]) == "合计"
            for ci, v in enumerate(r):
                cell(x, y, col_w[ci], row_h, v, S["cell"], bold, RED if (ri, ci) in t.red_cells else "black",
                     bg="#FAFAFA" if bold else None)
                x += col_w[ci]
            y += row_h
        y += 4
        for n in t.footnotes:
            ax.text(m, y + note_h / 2, n, ha="left", va="center_baseline", fontsize=S["note"], color="#555555",
                    fontproperties=self._fp())
            y += note_h
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=self.dpi, facecolor="white")
        plt.close(fig)
        return out
