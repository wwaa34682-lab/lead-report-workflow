from __future__ import annotations

import importlib

from .base import Notifier, NotifyError
from .outbox import AgentOutbox
from .webhooks import DingTalk, Email, FeishuApp, GenericWebhook, Slack, Teams, Telegram, WecomBot

REGISTRY = {c.type_name: c for c in (FeishuApp, WecomBot, DingTalk, Slack, Telegram, Email, GenericWebhook, Teams, AgentOutbox)}
REGISTRY["lark"] = FeishuApp
REGISTRY["wechat"] = AgentOutbox      # personal WeChat has no official bot API -> agent-operated


def build(cfg: dict, outbox_dir=None, dry_run=False) -> Notifier:
    """cfg = recipient.channel merged with {'id': recipient.id}."""
    t = cfg["type"]
    if dry_run or REGISTRY.get(t) is AgentOutbox:
        return AgentOutbox(cfg, outbox_dir)
    if t == "custom":
        mod, cls = cfg["class"].split(":")
        return getattr(importlib.import_module(mod), cls)(cfg)
    if t not in REGISTRY:
        raise ValueError(f"unknown channel type {t!r}; known: {sorted(REGISTRY)}")
    return REGISTRY[t](cfg)


__all__ = ["build", "Notifier", "NotifyError", "REGISTRY", "AgentOutbox"]
