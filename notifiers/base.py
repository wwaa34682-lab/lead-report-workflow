"""Notifier interface. Delivery is IMAGE-ONLY by default: tables go out as PNG images
(previewable in chat), never as file attachments, plus one short text caption.

Secrets come from environment variables named in config (`*_env` keys). Nothing secret in YAML.
"""
from __future__ import annotations

import json
import mimetypes
import os
import urllib.request
import uuid
from abc import ABC, abstractmethod
from pathlib import Path


class NotifyError(Exception):
    pass


def env(cfg: dict, key: str, required=True) -> str:
    name = cfg.get(key)
    val = os.environ.get(name, "") if name else ""
    if required and not val:
        raise NotifyError(f"channel {cfg.get('id')}: env var {name or '<'+key+' not set>'} is empty")
    return val


def http_json(url: str, payload: dict, headers: dict | None = None, timeout=30) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode() or "{}"
    try:
        return json.loads(text)
    except ValueError:
        return {"raw": text}


def http_multipart(url: str, fields: dict, files: dict[str, Path], headers: dict | None = None, timeout=60) -> dict:
    boundary = uuid.uuid4().hex
    body = bytearray()
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    for k, p in files.items():
        p = Path(p)
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{p.name}\"\r\n"
                 f"Content-Type: {ctype}\r\n\r\n").encode() + p.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(url, data=bytes(body), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode() or "{}"
    try:
        return json.loads(text)
    except ValueError:
        return {"raw": text}


class Notifier(ABC):
    type_name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.id = cfg["id"]

    @abstractmethod
    def send_text(self, text: str) -> None: ...

    @abstractmethod
    def send_image(self, path: Path) -> None: ...

    def send_file(self, path: Path) -> None:
        """Only used when a recipient explicitly asks for format: file. Default: fall back to image."""
        self.send_image(path)

    def deliver(self, images: list[Path], caption: str | None, fmt: str = "image") -> None:
        """fmt: image (images only) | image+text (caption then images) | file (as attachments)."""
        if caption and fmt != "image":
            self.send_text(caption)
        for p in images:
            (self.send_file if fmt == "file" else self.send_image)(Path(p))
