"""Daily / weekly WhatsApp summaries and a monthly PDF statement."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from .ledger import Ledger

LABELS = {"MTN": "MTN MoMo", "AIRTEL": "Airtel Money", "ZAMTEL": "Zamtel Money",
          "CASH": "Cash", "UNKNOWN": "Unknown network"}


def k(amount: float) -> str:
    return f"K{amount:,.2f}"


def _totals(rows):
    by_provider = defaultdict(float)
    money_in = money_out = 0.0
    for r in rows:
        if r["direction"] == "in":
            by_provider[r["provider"]] += r["amount"]
            money_in += r["amount"]
        else:
            money_out += r["amount"]
    return by_provider, money_in, money_out


def possible_duplicates(rows) -> list[tuple]:
    """Same amount + same sender within 10 minutes, where no transaction ID let us dedupe."""
    flagged = []
    rows = [r for r in rows if r["direction"] == "in"]
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if a["amount"] == b["amount"] and a["counterparty"] and a["counterparty"] == b["counterparty"] \
                    and (not a["reference"] or not b["reference"]):
                gap = abs(datetime.fromisoformat(b["occurred_at"]) - datetime.fromisoformat(a["occurred_at"]))
                if gap <= timedelta(minutes=10):
                    flagged.append((a, b))
    return flagged


def daily_summary(ledger: Ledger, phone: str, d: date) -> str:
    rows = ledger.day(phone, d)
    if not rows:
        return f"📒 {d:%a %d %b}: nothing recorded yet.\nForward your payment SMS here or type e.g. *sale 250 sugar*."
    by_provider, money_in, money_out = _totals(rows)
    digital = sum(v for p, v in by_provider.items() if p != "CASH")
    lines = [f"📒 *Takings for {d:%a %d %b}*", ""]
    for p in ("MTN", "AIRTEL", "ZAMTEL", "UNKNOWN", "CASH"):
        if by_provider.get(p):
            lines.append(f"{LABELS[p]}: {k(by_provider[p])}")
    lines += ["", f"*Total in: {k(money_in)}*",
              f"Digital {k(digital)} · Cash {k(by_provider.get('CASH', 0))}"]
    if money_out:
        lines.append(f"Money out: {k(money_out)}  →  Net {k(money_in - money_out)}")
    lines.append(f"{sum(1 for r in rows if r['direction'] == 'in')} payments in")

    checks = [r for r in rows if r["confidence"] == "check"]
    dups = possible_duplicates(rows)
    if checks or dups:
        lines += ["", "⚠️ *Please check*"]
        for r in checks:
            lines.append(f"• {k(r['amount'])} at {r['occurred_at'][11:16]} – couldn't fully read this SMS")
        for a, b in dups:
            lines.append(f"• {k(a['amount'])} from {a['counterparty']} appears twice "
                         f"({a['occurred_at'][11:16]} and {b['occurred_at'][11:16]})")
    return "\n".join(lines)


def week_summary(ledger: Ledger, phone: str, end: date) -> str:
    start = end - timedelta(days=6)
    lines = [f"📊 *Last 7 days ({start:%d %b} – {end:%d %b})*", ""]
    total = 0.0
    best = (None, 0.0)
    for i in range(7):
        d = start + timedelta(days=i)
        _, money_in, _ = _totals(ledger.day(phone, d))
        total += money_in
        if money_in > best[1]:
            best = (d, money_in)
        lines.append(f"{d:%a %d}: {k(money_in)}")
    lines += ["", f"*Week total: {k(total)}*", f"Daily average: {k(total / 7)}"]
    if best[0]:
        lines.append(f"Best day: {best[0]:%A} ({k(best[1])})")
    return "\n".join(lines)


def monthly_pdf(ledger: Ledger, phone: str, year: int, month: int, path: str) -> str:
    """Write a simple monthly statement a merchant can show a lender or ZRA."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    rows = ledger.between(phone, start, end)
    by_provider, money_in, money_out = _totals(rows)
    m = ledger.merchant(phone)
    styles = getSampleStyleSheet()

    story = [Paragraph(f"Monthly statement – {start:%B %Y}", styles["Title"]),
             Paragraph(f"{(m['name'] if m and m['name'] else 'Merchant')} · {phone}", styles["Normal"]),
             Paragraph("Compiled from payment SMS forwarded by the merchant and cash sales they recorded. "
                       "Not an operator or bank statement.", styles["Italic"]),
             Spacer(1, 12)]

    summary = [["Channel", "Money in"]] + \
              [[LABELS[p], k(v)] for p, v in sorted(by_provider.items())] + \
              [["Total in", k(money_in)], ["Money out", k(money_out)], ["Net", k(money_in - money_out)]]
    t = Table(summary, colWidths=[200, 120])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                           ("ALIGN", (1, 0), (1, -1), "RIGHT")]))
    story += [t, Spacer(1, 16)]

    detail = [["Date", "Channel", "In/Out", "Amount", "From / note", "Ref"]]
    for r in rows:
        detail.append([r["occurred_at"][:16].replace("T", " "), LABELS.get(r["provider"], r["provider"]),
                       r["direction"], k(r["amount"]), (r["counterparty"] or r["note"] or "")[:28],
                       r["reference"] or ""])
    d = Table(detail, repeatRows=1, colWidths=[85, 75, 40, 70, 140, 80])
    d.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("FONTSIZE", (0, 0), (-1, -1), 8),
                           ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                           ("ALIGN", (3, 0), (3, -1), "RIGHT")]))
    story.append(d)
    SimpleDocTemplate(path, pagesize=A4, title=f"Statement {start:%B %Y}").build(story)
    return path
