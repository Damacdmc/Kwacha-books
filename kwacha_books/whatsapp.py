"""Sending messages through Meta's WhatsApp Cloud API."""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("kwacha_books.whatsapp")


class WhatsApp:
    def __init__(self, token: str, phone_id: str, version: str = "v26.0"):
        self.token = token
        self.phone_id = phone_id
        self.base = f"https://graph.facebook.com/{version}"

    @classmethod
    def from_env(cls) -> "WhatsApp":
        return cls(os.environ.get("WA_TOKEN", ""), os.environ.get("WA_PHONE_ID", ""),
                   os.environ.get("WA_GRAPH_VERSION", "v26.0"))

    def _post(self, path: str, **kwargs) -> dict:
        r = requests.post(f"{self.base}/{self.phone_id}/{path}", timeout=20,
                          headers={"Authorization": f"Bearer {self.token}"}, **kwargs)
        if r.status_code >= 400:
            # Meta explains the problem in the body (expired token, number not allowed, etc.)
            log.error("WhatsApp API error %s on %s: %s", r.status_code, path, r.text[:500])
            r.raise_for_status()
        return r.json()

    def send_text(self, to: str, body: str) -> dict:
        return self._post("messages", json={
            "messaging_product": "whatsapp", "to": to, "type": "text",
            "text": {"body": body[:4096], "preview_url": False}})

    def send_document(self, to: str, path: str, caption: str) -> dict:
        name = os.path.basename(path)
        with open(path, "rb") as f:
            media = self._post("media", data={"messaging_product": "whatsapp", "type": "application/pdf"},
                               files={"file": (name, f, "application/pdf")})
        return self._post("messages", json={
            "messaging_product": "whatsapp", "to": to, "type": "document",
            "document": {"id": media["id"], "filename": name, "caption": caption[:1024]}})

    def send_template(self, to: str, name: str, language: str, params: list[str]) -> dict:
        return self._post("messages", json={
            "messaging_product": "whatsapp", "to": to, "type": "template",
            "template": {"name": name, "language": {"code": language},
                         "components": [{"type": "body",
                                         "parameters": [{"type": "text", "text": p} for p in params]}]}})

    def mark_read(self, message_id: str) -> None:
        try:
            self._post("messages", json={"messaging_product": "whatsapp", "status": "read",
                                         "message_id": message_id})
        except Exception:
            pass  # blue ticks are nice to have, never worth failing over
