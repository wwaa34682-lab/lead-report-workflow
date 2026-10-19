"""agent_outbox: for channels without a bot API (personal WeChat, WhatsApp, a DM to a boss...).
Writes outbox/<run_id>/<channel>.json; the AI agent (or a human) sends exactly those images, in order,
with its own messaging tool, then marks them sent. Also used for every channel in --dry-run."""
from __future__ import annotations

import json
from pathlib import Path

from .base import Notifier


class AgentOutbox(Notifier):
    type_name = "agent_outbox"

    def __init__(self, cfg, outbox_dir: Path | None = None):
        super().__init__(cfg)
        self.dir = Path(outbox_dir or "outbox")

    def send_text(self, text):  # pragma: no cover - deliver() handles both
        pass

    def send_image(self, path):  # pragma: no cover
        pass

    def deliver(self, images, caption, fmt="image"):
        self.dir.mkdir(parents=True, exist_ok=True)
        caption = caption if fmt != "image" else None   # image-only: no caption (alerts are passed with fmt=image+text)
        p = self.dir / f"{self.id}.json"
        if p.exists():  # same recipient, more batches in one run -> append
            old = json.loads(p.read_text(encoding="utf-8"))
            images = [*old["images"], *[str(i) for i in images]]
            caption = "\n".join(x for x in (old.get("caption"), caption) if x)
        p.write_text(json.dumps({
            "channel": self.id, "type": self.cfg.get("type"), "target": self.cfg.get("target_label", ""),
            "send_as": fmt, "caption": caption, "images": [str(i) for i in images], "status": "pending",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
