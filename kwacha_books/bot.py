"""Conversation logic. Pure function of (phone, text) -> replies, so it can be
driven by WhatsApp, the local simulator, or tests in exactly the same way."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from . import clock
from .ledger import DuplicateEntry, Ledger
from .parser import parse_note, parse_sms
from .reports import LABELS, daily_summary, k, monthly_pdf, week_summary

WELCOME = (
    "👋 Welcome to *Kwacha Books* – your shop's takings, counted for you.\n\n"
    "How it works:\n"
    "1. Forward every MTN, Airtel or Zamtel payment SMS to this chat.\n"
    "2. For cash, type e.g. *sale 250 sugar* or *expense 80 transport*.\n"
    "3. Each evening you get your totals.\n\n"
    "🔒 We only use your messages to keep your books. We never move money and never share "
    "your data without your permission. You can type *delete my data* at any time.\n\n"
    "Reply *YES* to agree and start."
)

HELP = (
    "*What you can send*\n"
    "• Forward a payment SMS → recorded\n"
    "• *sale 250 sugar* → cash sale\n"
    "• *expense 80 transport* → money out\n"
    "• *today* → today's totals\n"
    "• *week* → last 7 days\n"
    "• *statement* → this month's PDF\n"
    "• *undo* → remove the last entry\n"
    "• *delete my data* → erase everything"
)


@dataclass
class Reply:
    text: str
    document: Optional[str] = None   # path to a file to send (e.g. PDF statement)


@dataclass
class Summary:
    """An evening summary ready to send. kind="text" inside WhatsApp's 24-hour window,
    otherwise kind="template" with the parameters for the approved template."""
    phone: str
    kind: str
    text: str
    params: list = field(default_factory=list)


@dataclass
class Bot:
    ledger: Ledger
    pdf_dir: str = "statements"

    def handle(self, phone: str, text: str, now: Optional[datetime] = None) -> list[Reply]:
        now = now or clock.now()
        text = (text or "").strip()
        cmd = text.lower()
        m = self.ledger.ensure_merchant(phone, now)
        self.ledger.touch(phone, now)

        # ---- consent gate: nothing is stored until the merchant agrees ----
        if not m["consented"]:
            if cmd in ("yes", "y", "ndiyo", "ee", "eya"):
                self.ledger.set_consent(phone)
                return [Reply("✅ You're set up. Forward your first payment SMS now.\n\n" + HELP)]
            return [Reply(WELCOME)]

        # ---- data deletion (two-step confirmation) ----
        if cmd == "delete my data":
            self.ledger.set_pending_delete(phone, True)
            return [Reply("⚠️ This erases *all* your records and cannot be undone. Reply *CONFIRM DELETE* to continue.")]
        if cmd == "confirm delete" and m["pending_delete"]:
            self.ledger.forget(phone)
            return [Reply("🗑️ All your data has been deleted. Send any message to start again.")]
        if m["pending_delete"]:
            self.ledger.set_pending_delete(phone, False)

        # ---- commands ----
        if cmd in ("help", "menu", "?"):
            return [Reply(HELP)]
        if cmd in ("today", "summary", "total"):
            return [Reply(daily_summary(self.ledger, phone, now.date()))]
        if cmd in ("week", "7 days"):
            return [Reply(week_summary(self.ledger, phone, now.date()))]
        if cmd in ("statement", "report", "pdf"):
            os.makedirs(self.pdf_dir, exist_ok=True)
            path = os.path.join(self.pdf_dir, f"statement-{phone}-{now:%Y-%m}.pdf")
            monthly_pdf(self.ledger, phone, now.year, now.month, path)
            return [Reply(f"📄 Your statement for {now:%B %Y} is attached.", document=path)]
        if cmd == "undo":
            row = self.ledger.undo_last(phone)
            if not row:
                return [Reply("Nothing to undo.")]
            return [Reply(f"↩️ Removed: {k(row['amount'])} ({LABELS.get(row['provider'], row['provider'])}).")]

        # ---- records ----
        entry = parse_note(text) or parse_sms(text)
        if not entry:
            return [Reply("🤔 I couldn't read that. Forward the payment SMS exactly as you received it, "
                          "or type e.g. *sale 250 sugar*. Send *help* for options.")]
        try:
            self.ledger.add(phone, entry, now=now)
        except DuplicateEntry:
            return [Reply(f"ℹ️ Already recorded – transaction {entry.reference} is in your books.")]

        label = LABELS.get(entry.provider, entry.provider)
        if entry.direction == "in":
            msg = f"✅ {k(entry.amount)} received ({label})"
            if entry.counterparty:
                msg += f" from {entry.counterparty}"
            if entry.note:
                msg += f" – {entry.note}"
        else:
            msg = f"✅ {k(entry.amount)} out ({label})" + (f" – {entry.note}" if entry.note else "")
        if entry.occurred_at and entry.occurred_at.date() != now.date():
            msg += f"\n📅 Recorded for {entry.occurred_at:%a %d %b}, the date in the SMS."
        _, today_in = self._today_in(phone, now.date())
        msg += f"\nToday so far: {k(today_in)}"
        if entry.warnings:
            msg += "\n⚠️ " + "; ".join(entry.warnings) + ". Reply *undo* if this is wrong."
        return [Reply(msg)]

    def _today_in(self, phone: str, d: date):
        rows = self.ledger.day(phone, d)
        return rows, sum(r["amount"] for r in rows if r["direction"] == "in")

    def evening_summaries(self, now: Optional[datetime] = None) -> list[Summary]:
        """Summaries to push each evening (e.g. 19:00), one per merchant who recorded something today.

        WhatsApp lets a business send free-form text only within 24 hours of the customer's last
        message; after that it must use a pre-approved template. Merchants with nothing recorded
        today are skipped, so nobody gets a paid template saying "nothing today".
        Each merchant is claimed in the database, so a scheduler firing twice sends only once.
        """
        now = now or clock.now()
        d = now.date()
        out = []
        for m in self.ledger.all_merchants():
            rows = self.ledger.day(m["phone"], d)
            if not rows or not self.ledger.claim_summary(m["phone"], d, now):
                continue
            last = datetime.fromisoformat(m["last_inbound_at"]) if m["last_inbound_at"] else None
            text = daily_summary(self.ledger, m["phone"], d)
            if last and now - last < timedelta(hours=23, minutes=30):
                out.append(Summary(m["phone"], "text", text))
            else:
                by = {}
                for r in rows:
                    if r["direction"] == "in":
                        by[r["provider"]] = by.get(r["provider"], 0) + r["amount"]
                params = [f"{d:%a %d %b}", k(sum(by.values())), k(by.get("MTN", 0)), k(by.get("AIRTEL", 0)),
                          k(by.get("ZAMTEL", 0)), k(by.get("CASH", 0))]
                out.append(Summary(m["phone"], "template", text, params))
        return out
