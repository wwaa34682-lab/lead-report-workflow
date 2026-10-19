# notifiers

Interface: `Notifier.send_text`, `send_image`, optional `send_file`; `deliver(images, caption, fmt)`.
Implementations in `webhooks.py`: feishu/lark (app API), wecom_bot, dingtalk, slack, teams, telegram, email, webhook.
`outbox.py`: `agent_outbox` / `wechat` — writes a manifest for an AI agent or a human to send; also used for every
recipient in `--dry-run`. All credentials are read from environment variables named in the recipient's `channel`.

Note: the HTTP notifiers follow each platform's public API docs but were not exercised against live accounts in this
repo's tests — verify with `--dry-run` first, then a single test recipient.
