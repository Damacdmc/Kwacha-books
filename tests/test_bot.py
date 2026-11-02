from datetime import date, datetime

import pytest

from kwacha_books.bot import Bot
from kwacha_books.ledger import Ledger
from kwacha_books.parser import parse_note, parse_sms
from kwacha_books.reports import daily_summary

from .samples import NOT_PAYMENTS, SAMPLES

PHONE = "260970000001"
NOW = datetime(2026, 10, 28, 18, 0)


@pytest.mark.parametrize("sms,provider,direction,amount,ref", SAMPLES)
def test_parses_sample_sms(sms, provider, direction, amount, ref):
    e = parse_sms(sms)
    assert e is not None
    assert (e.provider, e.direction, e.amount, e.reference) == (provider, direction, amount, ref)
    assert e.confidence == "high"
    assert e.raw  # original kept for the merchant to check


def test_amount_is_transaction_not_balance():
    e = parse_sms(SAMPLES[0][0])
    assert e.amount == 250.00   # not the K1,320.50 balance


def test_counterparty_extracted():
    e = parse_sms(SAMPLES[0][0])
    assert "JOHN BANDA" in e.counterparty and "0961234567" in e.counterparty


@pytest.mark.parametrize("text", NOT_PAYMENTS)
def test_ignores_non_payments(text):
    assert parse_sms(text) is None


def test_unknown_network_is_flagged():
    e = parse_sms("You have received K75 from Ben 0960000000. Ref: XY12345")
    assert e.confidence == "check" and e.provider == "UNKNOWN"


def test_notes():
    e = parse_note("sale 250 sugar")
    assert (e.provider, e.direction, e.amount, e.note) == ("CASH", "in", 250.0, "sugar")
    e = parse_note("expense K80 transport")
    assert (e.direction, e.amount, e.note) == ("out", 80.0, "transport")
    assert parse_note("hello") is None


@pytest.fixture
def bot(tmp_path, db_url):
    return Bot(Ledger(db_url), pdf_dir=str(tmp_path / "pdf"))


def test_consent_required_before_recording(bot):
    r = bot.handle(PHONE, SAMPLES[0][0], now=NOW)
    assert "Reply *YES*" in r[0].text
    assert bot.ledger.day(PHONE, NOW.date()) == []
    bot.handle(PHONE, "yes", now=NOW)
    bot.handle(PHONE, SAMPLES[0][0], now=NOW)
    assert len(bot.ledger.day(PHONE, NOW.date())) == 1


def test_full_day_flow(bot):
    bot.handle(PHONE, "yes", now=NOW)
    for sms, *_ in SAMPLES:
        bot.handle(PHONE, sms, now=NOW)
    bot.handle(PHONE, "sale 250 sugar", now=NOW)
    # duplicate forward is caught
    r = bot.handle(PHONE, SAMPLES[0][0], now=NOW)
    assert "Already recorded" in r[0].text

    summary = bot.handle(PHONE, "today", now=NOW)[0].text
    # in: 250 + 1200 (MTN) + 85.50 + 40 (Airtel) + 500 (Zamtel) + 250 cash = 2325.50
    assert "MTN MoMo: K1,450.00" in summary
    assert "Airtel Money: K125.50" in summary
    assert "Zamtel Money: K500.00" in summary
    assert "Cash: K250.00" in summary
    assert "Total in: K2,325.50" in summary
    assert "Money out: K300.00" in summary
    assert "Net K2,025.50" in summary


def test_undo_and_statement(bot, tmp_path):
    bot.handle(PHONE, "yes", now=NOW)
    bot.handle(PHONE, "sale 100 bread", now=NOW)
    bot.handle(PHONE, "sale 999 typo", now=NOW)
    assert "K999.00" in bot.handle(PHONE, "undo", now=NOW)[0].text
    assert "Total in: K100.00" in daily_summary(bot.ledger, PHONE, NOW.date())
    r = bot.handle(PHONE, "statement", now=NOW)[0]
    assert r.document and r.document.endswith(".pdf")
    with open(r.document, "rb") as f:
        assert f.read(4) == b"%PDF"


def test_possible_duplicate_without_ref_flagged(bot):
    bot.handle(PHONE, "yes", now=NOW)
    sms = "MTN MoMo: You have received K60 from Ruth Daka 0961111111 on 2026-10-28 12:00"
    bot.handle(PHONE, sms, now=NOW)
    bot.handle(PHONE, sms.replace("12:00", "12:04"), now=NOW)
    s = daily_summary(bot.ledger, PHONE, date(2026, 10, 28))
    assert "appears twice" in s


def test_delete_my_data(bot):
    bot.handle(PHONE, "yes", now=NOW)
    bot.handle(PHONE, "sale 50 eggs", now=NOW)
    assert "CONFIRM DELETE" in bot.handle(PHONE, "delete my data", now=NOW)[0].text
    bot.handle(PHONE, "confirm delete", now=NOW)
    assert bot.ledger.merchant(PHONE) is None
