"""Ready-made channels. Each lists the env vars it needs; see docs/agent-workflow.md.

| type           | images how                                      | env vars                                        |
|----------------|-------------------------------------------------|-------------------------------------------------|
| feishu / lark  | app API: upload image -> image message          | FEISHU_APP_ID, FEISHU_APP_SECRET (+ receive_id) |
| wecom_bot      | group-robot webhook, image msg (base64+md5)     | WECOM_BOT_WEBHOOK                               |
| dingtalk       | robot webhook, markdown ![](public_url)         | DINGTALK_WEBHOOK (+ image_base_url hosting)     |
| slack          | bot token, files.getUploadURLExternal + complete| SLACK_BOT_TOKEN (+ channel_id)                  |
| telegram       | Bot API sendPhoto                               | TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID            |
| email          | SMTP, images inline (cid) in HTML body          | SMTP_HOST/PORT/USER/PASSWORD, MAIL_TO           |
| teams          | webhook Adaptive Card, image by hosted URL       | TEAMS_WEBHOOK (+ image_base_url)               |
| webhook        | generic multipart POST (file field "image")     | GENERIC_WEBHOOK_URL (+ optional token)          |
| agent_outbox   | writes an outbox manifest; an AI agent / human sends it via its own tools  | — |
"""
from __future__ import annotations

import base64
import hashlib
import json
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage
from pathlib import Path

from .base import Notifier, NotifyError, env, http_json, http_multipart


class FeishuApp(Notifier):
    type_name = "feishu"
    API = "https://open.feishu.cn/open-apis"   # Lark: https://open.larksuite.com/open-apis

    def _token(self):
        if getattr(self, "_tok", None):
            return self._tok
        base = self.cfg.get("api_base", self.API)
        r = http_json(f"{base}/auth/v3/tenant_access_token/internal",
                      {"app_id": env(self.cfg, "app_id_env"), "app_secret": env(self.cfg, "app_secret_env")})
        if r.get("code") != 0:
            raise NotifyError(f"feishu auth failed: {r.get('msg')}")
        self._tok = r["tenant_access_token"]
        return self._tok

    def _send(self, msg_type, content):
        base = self.cfg.get("api_base", self.API)
        rid_type = self.cfg.get("receive_id_type", "chat_id")      # chat_id | open_id | user_id | email
        r = http_json(f"{base}/im/v1/messages?receive_id_type={rid_type}",
                      {"receive_id": env(self.cfg, "receive_id_env"), "msg_type": msg_type, "content": json.dumps(content, ensure_ascii=False)},
                      {"Authorization": f"Bearer {self._token()}"})
        if r.get("code") != 0:
            raise NotifyError(f"feishu send failed: {r.get('msg')}")

    def send_text(self, text):
        self._send("text", {"text": text})

    def send_image(self, path):
        base = self.cfg.get("api_base", self.API)
        r = http_multipart(f"{base}/im/v1/images", {"image_type": "message"}, {"image": path},
                           {"Authorization": f"Bearer {self._token()}"})
        if r.get("code") != 0:
            raise NotifyError(f"feishu image upload failed: {r.get('msg')}")
        self._send("image", {"image_key": r["data"]["image_key"]})


class WecomBot(Notifier):
    type_name = "wecom_bot"

    def send_text(self, text):
        http_json(env(self.cfg, "webhook_env"), {"msgtype": "text", "text": {"content": text}})

    def send_image(self, path):
        b = Path(path).read_bytes()
        if len(b) > 2 * 1024 * 1024:
            raise NotifyError("wecom bot images must be <= 2MB; lower outputs.dpi")
        http_json(env(self.cfg, "webhook_env"), {"msgtype": "image", "image": {
            "base64": base64.b64encode(b).decode(), "md5": hashlib.md5(b).hexdigest()}})


class DingTalk(Notifier):
    type_name = "dingtalk"

    def send_text(self, text):
        http_json(env(self.cfg, "webhook_env"), {"msgtype": "text", "text": {"content": text}})

    def send_image(self, path):
        base = self.cfg.get("image_base_url")
        if not base:
            raise NotifyError("dingtalk robot cannot upload images; set image_base_url to where PNGs are hosted")
        http_json(env(self.cfg, "webhook_env"), {"msgtype": "markdown", "markdown": {
            "title": Path(path).stem, "text": f"![]({base.rstrip('/')}/{Path(path).name})"}})


class Slack(Notifier):
    type_name = "slack"

    def _h(self):
        return {"Authorization": f"Bearer {env(self.cfg, 'token_env')}"}

    def send_text(self, text):
        http_json("https://slack.com/api/chat.postMessage", {"channel": env(self.cfg, "channel_env"), "text": text}, self._h())

    def send_image(self, path):
        p = Path(path)
        q = f"filename={p.name}&length={p.stat().st_size}"
        req = urllib.request.Request(f"https://slack.com/api/files.getUploadURLExternal?{q}", headers=self._h())
        with urllib.request.urlopen(req, timeout=30) as r:
            meta = json.loads(r.read())
        if not meta.get("ok"):
            raise NotifyError(f"slack: {meta.get('error')}")
        urllib.request.urlopen(urllib.request.Request(meta["upload_url"], data=p.read_bytes(), method="POST"), timeout=60)
        http_json("https://slack.com/api/files.completeUploadExternal",
                  {"files": [{"id": meta["file_id"], "title": p.stem}], "channel_id": env(self.cfg, "channel_env")}, self._h())


class Telegram(Notifier):
    type_name = "telegram"

    def _url(self, m):
        return f"https://api.telegram.org/bot{env(self.cfg, 'token_env')}/{m}"

    def send_text(self, text):
        http_json(self._url("sendMessage"), {"chat_id": env(self.cfg, "chat_id_env"), "text": text})

    def send_image(self, path):
        http_multipart(self._url("sendPhoto"), {"chat_id": env(self.cfg, "chat_id_env")}, {"photo": path})


class Email(Notifier):
    """Collects text + images and sends ONE mail with inline images on flush()."""
    type_name = "email"

    def __init__(self, cfg):
        super().__init__(cfg)
        self._text, self._imgs = [], []

    def send_text(self, text):
        self._text.append(text)

    def send_image(self, path):
        self._imgs.append(Path(path))

    def deliver(self, images, caption, fmt="image"):
        super().deliver(images, caption, "image+text" if caption else fmt)
        msg = EmailMessage()
        msg["Subject"] = self.cfg.get("subject", "Daily lead report")
        msg["From"] = env(self.cfg, "from_env", required=False) or env(self.cfg, "user_env")
        msg["To"] = env(self.cfg, "to_env")
        msg.set_content("\n".join(self._text))
        html = "".join(f"<p>{t}</p>" for t in self._text) + "".join(f'<p><img src="cid:img{i}"></p>' for i in range(len(self._imgs)))
        msg.add_alternative(html, subtype="html")
        part = msg.get_payload()[1]
        for i, p in enumerate(self._imgs):
            part.add_related(p.read_bytes(), "image", "png", cid=f"<img{i}>")
        with smtplib.SMTP(env(self.cfg, "host_env"), int(env(self.cfg, "port_env", required=False) or 587)) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(env(self.cfg, "user_env"), env(self.cfg, "password_env"))
            s.send_message(msg)


class GenericWebhook(Notifier):
    type_name = "webhook"

    def _h(self):
        tok = env(self.cfg, "token_env", required=False) if self.cfg.get("token_env") else ""
        return {"Authorization": f"Bearer {tok}"} if tok else {}

    def send_text(self, text):
        http_json(env(self.cfg, "url_env"), {"type": "text", "text": text}, self._h())

    def send_image(self, path):
        http_multipart(env(self.cfg, "url_env"), {"type": "image"}, {"image": path}, self._h())


class Teams(Notifier):
    """Microsoft Teams via Incoming Webhook / Workflows webhook (Adaptive Card).
    Webhooks cannot upload files, so images are referenced by URL: set image_base_url
    (where PNGs are hosted) — or inline_data_uri: true for small images (Teams may reject > ~28KB cards)."""
    type_name = "teams"

    def _card(self, body):
        return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive",
                "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard",
                            "version": "1.4", "body": body}}]}

    def send_text(self, text):
        http_json(env(self.cfg, "webhook_env"), self._card([{"type": "TextBlock", "text": text, "wrap": True}]))

    def send_image(self, path):
        p = Path(path)
        if self.cfg.get("image_base_url"):
            url = f"{self.cfg['image_base_url'].rstrip('/')}/{p.name}"
        elif self.cfg.get("inline_data_uri"):
            url = "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
        else:
            raise NotifyError("teams: set image_base_url (hosted PNGs) or inline_data_uri: true")
        http_json(env(self.cfg, "webhook_env"), self._card([{"type": "Image", "url": url}]))
