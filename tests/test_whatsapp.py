"""The WhatsApp webhook, driven with the same JSON Meta sends, and a fake sender instead of Meta."""
import hashlib
import hmac
import itertools
import json
import os
from datetime import datetime, timedelta

import pytest

import app as app_module
from kwacha_books import clock
from kwacha_books.bot import Bot
from kwacha_books.ledger import Ledger

from .samples import SAMPLES

MERCHANT = "260970000001"
# an SMS with no date in it, so it counts for today
TODAY_SMS = ("You have received ZMW 250.00 from JOHN BANDA 0961234567. Transaction ID: 4419328871. "
             "Your new balance is ZMW 1,320.50. MTN MoMo")
SECRET = "test-app-secret"
_ids = itertools.count(1)


class FakeWhatsApp:
    def __init__(self):
        self.sent = []          # (kind, to, content)
        self.fail = False

    def send_text(self, to, body):
        if self.fail:
            raise RuntimeError("Meta is down")
        self.sent.append(("text", to, body))

    def send_document(self, to, path, caption):
        assert os.path.exists(path)
        self.sent.append(("document", to, caption))

    def send_template(self, to, name, language, params):
        self.sent.append(("template", to, (name, language, params)))

    def mark_read(self, message_id):
        pass

    def texts(self):
        return [c for k, _, c in self.sent if k == "text"]


def payload(text=None, sender=MERCHANT, kind="text", msg_id=None):
    msg = {"from": sender, "id": msg_id or f"wamid.TEST{next(_ids)}", "timestamp": "1793300000", "type": kind}
    if kind == "text":
        msg["text"] = {"body": text}
    else:
        msg[kind] = {"id": "media123", "mime_type": "image/jpeg"}
    return {"object": "whatsapp_business_account", "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"phone_number_id": "PHONE_ID"},
        "contacts": [{"wa_id": sender, "profile": {"name": "Test Shop"}}], "messages": [msg]}}]}]}


@pytest.fixture
def setup(db_url):
    wa = FakeWhatsApp()
    ledger = Ledger(db_url)
    env = {"WA_VERIFY_TOKEN": "verify-me", "WA_APP_SECRET": SECRET, "TASK_TOKEN": "task-secret"}
    flask_app = app_module.create_app(ledger=ledger, wa=wa, env=env)
    client = flask_app.test_client()

    def post(body, secret=SECRET):
        raw = json.dumps(body).encode()
        sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return client.post("/webhook", data=raw, content_type="application/json",
                           headers={"X-Hub-Signature-256": sig})

    def say(text, **kw):
        assert post(payload(text, **kw)).status_code == 200

    return client, wa, ledger, post, say


def test_webhook_verification(setup):
    client, *_ = setup
    ok = client.get("/webhook?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=12345")
    assert ok.status_code == 200 and ok.data == b"12345"
    assert client.get("/webhook?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=1").status_code == 403


def test_bad_signature_rejected(setup):
    _, wa, _, post, _ = setup
    assert post(payload("hi"), secret="not-the-secret").status_code == 403
    assert wa.sent == []


def test_full_conversation(setup):
    _, wa, ledger, _, say = setup
    say("hi")
    assert "Reply *YES*" in wa.texts()[-1]
    say("yes")
    say(TODAY_SMS)
    assert "K250.00 received (MTN MoMo)" in wa.texts()[-1]
    say("sale 120 sugar")
    say("today")
    assert "Total in: K370.00" in wa.texts()[-1]
    say("statement")
    assert wa.sent[-1][0] == "document"


def test_meta_retry_is_ignored(setup):
    _, wa, ledger, post, say = setup
    say("yes")
    body = payload(SAMPLES[2][0], msg_id="wamid.SAME")
    post(body)
    post(body)   # Meta re-delivers the same message
    assert len([t for t in wa.texts() if "received (Airtel Money)" in t]) == 1
    assert len(ledger.between(MERCHANT, clock.now().date().replace(year=2000), clock.now().date() + timedelta(days=1))) == 1


def test_status_updates_and_photos(setup):
    _, wa, _, post, say = setup
    status_only = {"entry": [{"changes": [{"value": {"statuses": [{"id": "x", "status": "delivered"}]}}]}]}
    assert post(status_only).status_code == 200 and wa.sent == []
    say(None, kind="image")
    assert "only read the *text*" in wa.texts()[-1]


def test_pilot_allowlist(db_url):
    wa = FakeWhatsApp()
    env = {"ALLOWED_NUMBERS": "+260970000001, 260960000002", "TASK_TOKEN": "t"}
    client = app_module.create_app(ledger=Ledger(db_url), wa=wa, env=env).test_client()
    client.post("/webhook", json=payload("hi", sender="260955555555"))
    assert "small pilot" in wa.texts()[-1]
    client.post("/webhook", json=payload("hi", sender="260970000001"))
    assert "Welcome" in wa.texts()[-1]


def test_error_reply_when_something_breaks(setup, monkeypatch):
    _, wa, _, _, say = setup
    monkeypatch.setattr(Bot, "handle", lambda *a, **k: 1 / 0)
    say("hi")
    assert "something went wrong" in wa.texts()[-1]


def test_evening_summaries(setup):
    client, wa, ledger, _, say = setup
    other = "260960000002"
    for who in (MERCHANT, other):
        say("yes", sender=who)
        say("sale 100 bread", sender=who)
    # the other merchant last wrote 2 days ago: outside the 24-hour window
    ledger.touch(other, clock.now() - timedelta(days=2))
    say("yes", sender="260950000003")          # agreed but recorded nothing: no summary

    assert client.post("/tasks/evening-summaries").status_code == 403
    r = client.post("/tasks/evening-summaries", headers={"X-Task-Token": "task-secret"}).get_json()
    assert r == {"sent": 2, "failed": 0}
    kinds = {to: kind for kind, to, _ in wa.sent[-2:]}
    assert kinds == {MERCHANT: "text", other: "template"}
    name, lang, params = wa.sent[-1][2] if wa.sent[-1][1] == other else wa.sent[-2][2]
    assert name == "daily_summary" and params[1] == "K100.00" and params[5] == "K100.00"

    # scheduler fires twice: nothing is sent again
    again = client.post("/tasks/evening-summaries?token=task-secret").get_json()
    assert again == {"sent": 0, "failed": 0}


def test_failed_summary_can_retry(setup):
    client, wa, ledger, _, say = setup
    say("yes")
    say("sale 50 eggs")
    wa.fail = True
    assert client.post("/tasks/evening-summaries?token=task-secret").get_json() == {"sent": 0, "failed": 1}
    wa.fail = False
    assert client.post("/tasks/evening-summaries?token=task-secret").get_json() == {"sent": 1, "failed": 0}


def test_health_and_stats(setup):
    client, *_ , say = setup
    say("yes")
    assert client.get("/health").get_json() == {"ok": True}
    assert client.get("/admin/stats").status_code == 403
    assert client.get("/admin/stats?token=task-secret").get_json()["consented"] == 1


def test_sms_with_old_date(setup):
    _, wa, _, _, say = setup
    say("yes")
    say("MTN MoMo: You have received K60 from Ruth Daka 0961111111 on 2020-01-05 12:00. Ref: OLD12345")
    assert "Recorded for Sun 05 Jan" in wa.texts()[-1]


def test_privacy_page_and_short_template(db_url):
    wa = FakeWhatsApp()
    env = {"TASK_TOKEN": "t", "WA_SUMMARY_PARAM_COUNT": "2", "BUSINESS_NAME": "Kwacha <Books>"}
    client = app_module.create_app(ledger=Ledger(db_url), wa=wa, env=env).test_client()
    page = client.get("/privacy")
    assert page.status_code == 200 and b"Kwacha &lt;Books&gt; privacy policy" in page.data
    client.post("/webhook", json=payload("yes"))
    client.post("/webhook", json=payload("sale 40 salt"))
    Ledger(db_url).touch(MERCHANT, clock.now() - timedelta(days=3))
    client.post("/tasks/evening-summaries?token=t")
    kind, _, (name, lang, params) = wa.sent[-1]
    assert kind == "template" and len(params) == 2 and params[1] == "K40.00"
