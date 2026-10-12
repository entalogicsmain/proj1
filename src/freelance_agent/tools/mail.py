"""Email sending. Real Gmail via REST + OAuth refresh token; DryRunSender for tests and dry runs."""
from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Protocol

from ..secrets_store import get_secret


class Sender(Protocol):
    def send(self, to: str, subject: str, body: str) -> str: ...


class DryRunSender:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, to: str, subject: str, body: str) -> str:
        self.sent.append({"to": to, "subject": subject, "body": body})
        return f"dry-{len(self.sent)}"


class GmailSender:
    """Needs secrets GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN, GMAIL_ADDRESS.
    Not exercised by tests (no network); verify with a single send to the owner before enabling."""

    def _access_token(self) -> str:
        data = urllib.parse.urlencode({
            "client_id": get_secret("GMAIL_CLIENT_ID"), "client_secret": get_secret("GMAIL_CLIENT_SECRET"),
            "refresh_token": get_secret("GMAIL_REFRESH_TOKEN"), "grant_type": "refresh_token"}).encode()
        with urllib.request.urlopen("https://oauth2.googleapis.com/token", data, timeout=30) as r:
            return json.loads(r.read())["access_token"]

    def send(self, to: str, subject: str, body: str) -> str:
        msg = EmailMessage()
        msg["To"], msg["From"], msg["Subject"] = to, get_secret("GMAIL_ADDRESS"), subject
        msg["List-Unsubscribe"] = f"<mailto:{get_secret('GMAIL_ADDRESS')}?subject=unsubscribe>"
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        req = urllib.request.Request(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            data=json.dumps({"raw": raw}).encode(),
            headers={"Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["id"]
