# Kwacha Books – WhatsApp bookkeeper

Merchants forward MTN MoMo, Airtel Money and Zamtel Money payment SMS to a WhatsApp
number. The bot records each payment, catches duplicates, logs cash sales typed as
`sale 250 sugar`, and sends daily and weekly totals plus a monthly PDF statement.

It never holds or moves money. It only reads messages the merchant chooses to send.

**To put it on real WhatsApp, follow [SETUP_WHATSAPP.md](SETUP_WHATSAPP.md).**

## What's included

| File | Purpose |
|---|---|
| `kwacha_books/parser.py` | Reads payment SMS and quick notes into structured entries |
| `kwacha_books/ledger.py` | Storage (SQLite locally, PostgreSQL in the cloud), duplicates, undo, delete-my-data |
| `kwacha_books/reports.py` | Daily/weekly summaries, monthly PDF statement |
| `kwacha_books/bot.py` | Conversation logic: consent, commands, replies, evening summaries |
| `kwacha_books/whatsapp.py` | Sends text, PDFs and template messages through Meta's WhatsApp Cloud API |
| `kwacha_books/clock.py` | Zambia time, whatever timezone the server is in |
| `app.py` | The live WhatsApp server: webhook, evening summaries, privacy page, health check |
| `render.yaml` | One-click deployment on Render (web service + PostgreSQL) |
| `SETUP_WHATSAPP.md` | Step-by-step guide: Meta, GitHub, Render, templates, scheduling |
| `web.py` + `web/index.html` | Chat with the bot in your browser on your own computer |
| `simulate.py` | Chat with the bot in a terminal |
| `tests/` | 33 tests, including simulated WhatsApp webhooks; `samples.py` holds example SMS |

## Try it on your computer

```bash
pip install -r requirements.txt
python web.py               # then open http://localhost:8000 in your browser
python simulate.py          # or chat in the terminal instead
python -m pytest -q         # run the tests (33 should pass)
```

The web page keeps its records in `web_demo.db` and statements in `statements/`.
Press Ctrl+C in the terminal to stop it. "Erase and start over" on the page clears the records.

## How the live server behaves

- **Consent first:** nothing is stored until the merchant replies YES. "delete my data" erases everything.
- **Meta retries are ignored:** each WhatsApp message ID is handled once, so a merchant never gets double replies.
- **Duplicate SMS are caught** by transaction ID, even if two arrive at the same moment.
- **Fake requests are rejected:** every webhook call must carry Meta's signature (set WA_APP_SECRET).
- **Pilot mode:** set ALLOWED_NUMBERS and only those numbers can use the bot.
- **Evening summaries** (`POST /tasks/evening-summaries`, protected by TASK_TOKEN): normal text for merchants
  who messaged in the last 24 hours, the approved `daily_summary` template for others, nothing for merchants
  with no records that day, and never more than one per merchant per day.
- **Photos and PDFs** get a polite reply asking for the SMS text instead.
- **Dates:** SMS with a date in them are recorded on that date; everything else uses Zambia time.

## Before a pilot: must-do

- **Replace the sample SMS with real ones.** The SMS in `tests/samples.py` are illustrative,
  not copies of real operator messages. Collect real ones from all three networks during the
  merchant interviews (remove names and numbers), add them to `samples.py`, and adjust the
  patterns in `parser.py` until every one parses. This is the single most important step.
- **Data protection.** Register with Zambia's Office of the Data Protection Commissioner and have the
  `/privacy` page reviewed. Check which database backups your Render plan includes.
- **Levy and tax estimates** are not included. Add them once the current Mobile Money Transaction
  Levy bands and the relevant tax rules are confirmed with ZRA or an accountant.
- **Later:** reading screenshots and PDFs with an AI model, always confirmed by the merchant before saving.
