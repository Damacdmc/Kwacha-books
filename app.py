"""Kwacha Books on real WhatsApp (Meta WhatsApp Cloud API).

Settings come from environment variables (see .env.example and SETUP_WHATSAPP.md):
  WA_TOKEN            access token for your WhatsApp Business app
  WA_PHONE_ID         phone-number ID from Meta's WhatsApp > API Setup page
  WA_VERIFY_TOKEN     any secret string; enter the same one when registering the webhook
  WA_APP_SECRET       your Meta app's secret, used to prove messages really come from Meta
  DATABASE_URL        postgresql://... in the cloud (default: a local SQLite file)
  TASK_TOKEN          secret that the evening-summary scheduler must send
  ALLOWED_NUMBERS     optional, comma-separated: only these numbers may use the bot (pilot)
  WA_SUMMARY_TEMPLATE name of the approved summary template (default daily_summary)

Local run:   python app.py        Cloud: gunicorn "app:create_app()" (see render.yaml)
"""
from __future__ import annotations

import hashlib
import hmac
import html
import logging
import os
import tempfile

from flask import Flask, abort, jsonify, request

from kwacha_books import clock
from kwacha_books.bot import Bot
from kwacha_books.ledger import Ledger
from kwacha_books.whatsapp import WhatsApp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("kwacha_books.app")

PILOT_ONLY = ("👋 Thanks for your interest in Kwacha Books! We're running a small pilot at the moment. "
              "We'll message you when it opens to more shops.")
SMS_ONLY = ("📷 Thanks! For now I can only read the *text* of payment messages. Open the SMS, "
            "copy or share it, and paste it here. Photos and PDFs are coming later.")
ERROR = "😕 Sorry, something went wrong on my side. Please send that again in a minute."

PRIVACY_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{business} – Privacy policy</title>
<style>body{{font-family:Arial,sans-serif;max-width:680px;margin:40px auto;padding:0 16px;line-height:1.55;color:#10261F}}</style>
</head><body>
<h1>{business} privacy policy</h1>
<p>{business} is a WhatsApp bookkeeping service for shops and traders in Zambia.</p>
<h2>What we collect</h2>
<p>Your WhatsApp number, the messages you choose to send us (such as forwarded mobile money SMS and notes like
"sale 250 sugar"), and the records we create from them: amounts, dates, network, transaction IDs and the names or
numbers that appear in those messages.</p>
<h2>How we use it</h2>
<p>Only to keep your books: to record payments, send you daily, weekly and monthly summaries, and make statements
you ask for. We never move money, never ask for your PIN, and never sell your data.</p>
<h2>Who we share it with</h2>
<p>Messages travel through WhatsApp (Meta) and are stored with our hosting provider. We share your records with
anyone else, such as a lender, only when you ask us to.</p>
<h2>Your choices</h2>
<p>Nothing is stored until you reply YES. Send "delete my data" at any time to erase all your records.</p>
<h2>Contact</h2>
<p>Questions or requests: {contact}</p>
</body></html>"""


def create_app(ledger: Ledger | None = None, wa: WhatsApp | None = None, env: dict | None = None) -> Flask:
    env = env if env is not None else os.environ
    ledger = ledger or Ledger(env.get("DATABASE_URL", "kwacha_books.db"))
    wa = wa or WhatsApp.from_env()
    bot = Bot(ledger, pdf_dir=os.path.join(tempfile.gettempdir(), "kwacha_statements"))
    verify_token = env.get("WA_VERIFY_TOKEN", "")
    app_secret = env.get("WA_APP_SECRET", "")
    task_token = env.get("TASK_TOKEN", "")
    template = env.get("WA_SUMMARY_TEMPLATE", "daily_summary")
    template_lang = env.get("WA_SUMMARY_TEMPLATE_LANG", "en")
    # 6 = date, total, MTN, Airtel, Zamtel, cash. Use 2 (date, total) if Meta asks for fewer variables.
    template_params = int(env.get("WA_SUMMARY_PARAM_COUNT", "6"))
    business = env.get("BUSINESS_NAME", "Kwacha Books")
    contact = env.get("CONTACT_EMAIL", "[your email]")
    allowed = {n.strip().lstrip("+") for n in env.get("ALLOWED_NUMBERS", "").split(",") if n.strip()}
    if not app_secret:
        log.warning("WA_APP_SECRET is not set: anyone could post fake messages to /webhook. Set it before going live.")

    app = Flask(__name__)

    @app.get("/")
    def home():
        return "Kwacha Books is running."

    @app.get("/privacy")
    def privacy():
        # Meta asks for a privacy policy link before the app can go live. Have it reviewed before launch.
        return PRIVACY_HTML.format(business=html.escape(business), contact=html.escape(contact))

    @app.get("/health")
    def health():
        ledger.stats()   # fails if the database is unreachable
        return jsonify(ok=True)

    # ---- Meta checks the webhook once when you register it ----
    @app.get("/webhook")
    def verify():
        if request.args.get("hub.mode") == "subscribe" and verify_token \
                and hmac.compare_digest(request.args.get("hub.verify_token", ""), verify_token):
            return request.args.get("hub.challenge", "")
        abort(403)

    # ---- every incoming message ----
    @app.post("/webhook")
    def receive():
        if app_secret:
            sig = request.headers.get("X-Hub-Signature-256", "")
            expected = "sha256=" + hmac.new(app_secret.encode(), request.get_data(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                log.warning("Rejected a webhook call with a bad signature")
                abort(403)

        payload = request.get_json(silent=True) or {}
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    handle_message(msg)
        # Always answer 200 quickly, or Meta keeps retrying the same message.
        return "ok"

    def handle_message(msg: dict) -> None:
        sender, msg_id, kind = msg.get("from", ""), msg.get("id", ""), msg.get("type")
        if not sender or not msg_id or not ledger.first_time_seen(msg_id, clock.now()):
            return  # Meta re-delivered a message we already handled
        wa.mark_read(msg_id)
        try:
            if allowed and sender not in allowed:
                wa.send_text(sender, PILOT_ONLY)
                return
            if kind != "text":
                wa.send_text(sender, SMS_ONLY)
                return
            for reply in bot.handle(sender, msg["text"]["body"]):
                if reply.document:
                    wa.send_document(sender, reply.document, reply.text)
                    os.remove(reply.document)
                else:
                    wa.send_text(sender, reply.text)
        except Exception:
            log.exception("Failed to handle message %s", msg_id)
            try:
                wa.send_text(sender, ERROR)
            except Exception:
                pass

    # ---- evening summaries, called by a scheduler at e.g. 19:00 Zambia time ----
    def run_summaries() -> dict:
        sent = failed = 0
        for s in bot.evening_summaries(clock.now()):
            try:
                if s.kind == "text":
                    wa.send_text(s.phone, s.text)
                else:
                    wa.send_template(s.phone, template, template_lang, s.params[:template_params])
                sent += 1
            except Exception:
                failed += 1
                ledger.release_summary(s.phone, clock.now().date())   # allow a retry
                log.exception("Summary to %s failed", s.phone)
        return {"sent": sent, "failed": failed}

    @app.post("/tasks/evening-summaries")
    def summaries():
        given = request.headers.get("X-Task-Token") or request.args.get("token", "")
        if not task_token or not hmac.compare_digest(given, task_token):
            abort(403)
        return jsonify(run_summaries())

    @app.get("/admin/stats")
    def stats():
        if not task_token or not hmac.compare_digest(request.args.get("token", ""), task_token):
            abort(403)
        return jsonify(ledger.stats())

    @app.cli.command("send-summaries")
    def send_summaries_cmd():
        print(run_summaries())

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
