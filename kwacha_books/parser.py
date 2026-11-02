"""Turn forwarded mobile-money SMS and quick notes into structured entries.

IMPORTANT: the SMS patterns below are written to tolerate common wording
("You have received ZMW 250.00 from ...", "Money received K250 from ...") but
they are NOT copies of real operator messages. Before a pilot, collect real
samples from MTN MoMo, Airtel Money and Zamtel Money and add them to
tests/samples.py, then adjust the patterns until every sample parses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

PROVIDERS = ("MTN", "AIRTEL", "ZAMTEL", "CASH")


@dataclass
class Entry:
    provider: str              # MTN / AIRTEL / ZAMTEL / CASH
    direction: str             # "in" (money received) or "out" (money paid out)
    amount: float              # kwacha
    counterparty: str = ""     # sender name or phone
    reference: str = ""        # operator transaction id, used to catch duplicates
    note: str = ""             # free text, e.g. "sugar"
    occurred_at: Optional[datetime] = None
    raw: str = ""              # original message, always kept so merchants can check
    confidence: str = "high"   # "high" = matched a rule; "check" = needs merchant confirmation
    warnings: list = field(default_factory=list)


# ---------- helpers ----------

_AMOUNT = r"(?:ZMW|ZMK|K)\s?(?P<amount>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
_REF = r"(?:Trans(?:action)?\.?\s?(?:ID|Id|id|Ref|ref)|TxnId|Txn ID|Ref(?:erence)?|ID)[:.\s#]*(?P<ref>[A-Za-z0-9.]{5,})"
_PHONE = r"(?P<phone>(?:\+?260|0)\d{9})"


def _to_amount(text: str) -> float:
    return round(float(text.replace(",", "")), 2)


def _detect_provider(text: str) -> Optional[str]:
    t = text.upper()
    if "MOMO" in t or "MTN" in t:
        return "MTN"
    if "AIRTEL" in t:
        return "AIRTEL"
    if "ZAMTEL" in t:
        return "ZAMTEL"
    return None


def _find_datetime(text: str) -> Optional[datetime]:
    patterns = [
        (r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)", ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]),
        (r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}(?::\d{2})?)", ["%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"]),
        (r"(\d{2}-\d{2}-\d{4})\s+(\d{2}:\d{2}(?::\d{2})?)", ["%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M"]),
    ]
    for pat, fmts in patterns:
        m = re.search(pat, text)
        if m:
            stamp = f"{m.group(1)} {m.group(2)}"
            for fmt in fmts:
                try:
                    return datetime.strptime(stamp, fmt)
                except ValueError:
                    continue
    return None


# ---------- mobile money SMS ----------

_IN_WORDS = r"(?:received|receive|credited|deposit(?:ed)?|payment\s+of|paid\s+you)"
_OUT_WORDS = r"(?:sent|paid|withdr[ae]w(?:n|al)?|cash\s?out|debited|transferred)"


def parse_sms(text: str) -> Optional[Entry]:
    """Parse a forwarded payment SMS. Returns None if it isn't one."""
    clean = " ".join(text.split())
    amount_m = re.search(_AMOUNT, clean, re.IGNORECASE)
    if not amount_m:
        return None

    provider = _detect_provider(clean)
    lower = clean.lower()
    is_in = re.search(_IN_WORDS, lower) is not None
    is_out = re.search(_OUT_WORDS, lower) is not None
    if not (is_in or is_out):
        return None

    # "received" wins when both appear ("You have received ... sent by ...")
    direction = "in" if is_in else "out"

    # the transaction amount is the first amount; balances come later in the SMS
    amount = _to_amount(amount_m.group("amount"))

    counterparty = ""
    word = r"\bfrom\b" if direction == "in" else r"\bto\b"
    stop = r"(?=\s*(?:\(|,|\.|\+?\d|\s(?:on|at|Trans\w*|Ref\w*|ID|TxnId)\b|$))"
    who = re.search(word + r"\s+(?P<who>[A-Za-z][A-Za-z '-]{1,40}?)" + stop, clean, re.IGNORECASE)
    if who:
        counterparty = who.group("who").strip()
    phone = re.search(_PHONE, clean)
    if phone:
        counterparty = f"{counterparty} ({phone.group('phone')})".strip() if counterparty else phone.group("phone")

    ref_m = re.search(_REF, clean)
    reference = ref_m.group("ref").rstrip(".") if ref_m else ""

    entry = Entry(
        provider=provider or "MTN",
        direction=direction,
        amount=amount,
        counterparty=counterparty,
        reference=reference,
        occurred_at=_find_datetime(clean),
        raw=text.strip(),
    )
    if provider is None:
        entry.confidence = "check"
        entry.warnings.append("Could not tell which network this is from")
        entry.provider = "UNKNOWN"
    if not reference:
        entry.confidence = "check"
        entry.warnings.append("No transaction ID, so duplicates can't be caught")
    return entry


# ---------- quick notes typed by the merchant ----------

_NOTE = re.compile(
    r"^\s*(?P<kind>sale|sold|cash|in|expense|spent|paid|out)\s+"
    r"(?:K|ZMW)?\s?(?P<amount>\d+(?:[.,]\d{1,2})?)\s*(?P<note>.*)$",
    re.IGNORECASE,
)


def parse_note(text: str) -> Optional[Entry]:
    """Parse 'sale 250 sugar' (cash in) or 'expense 80 transport' (cash out)."""
    m = _NOTE.match(text)
    if not m:
        return None
    kind = m.group("kind").lower()
    direction = "out" if kind in ("expense", "spent", "paid", "out") else "in"
    return Entry(
        provider="CASH",
        direction=direction,
        amount=_to_amount(m.group("amount").replace(",", ".")),
        note=m.group("note").strip(),
        raw=text.strip(),
    )
