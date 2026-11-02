"""Browser version of the simulator: chat with the real bot in a phone-style window.

    python web.py
    then open http://localhost:8000

Everything stays on your computer. Records are saved in web_demo.db.
"""
from __future__ import annotations

import os
from kwacha_books import clock

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from kwacha_books.bot import Bot
from kwacha_books.ledger import Ledger
from kwacha_books.reports import LABELS

HERE = os.path.dirname(os.path.abspath(__file__))
PHONE = "260970000001"   # the one test merchant this page plays


def create_app(db_path: str = os.path.join(HERE, "web_demo.db"),
               pdf_dir: str = os.path.join(HERE, "statements")) -> Flask:
    app = Flask(__name__, static_folder=None)
    state = {"bot": Bot(Ledger(db_path), pdf_dir=pdf_dir)}

    def bot() -> Bot:
        return state["bot"]

    @app.get("/")
    def index():
        return send_from_directory(os.path.join(HERE, "web"), "index.html")

    @app.post("/api/message")
    def message():
        text = (request.get_json(silent=True) or {}).get("text", "")
        if not text.strip():
            return jsonify(replies=[])
        replies = []
        for r in bot().handle(PHONE, text):
            item = {"text": r.text}
            if r.document:
                item["document"] = "/api/statement/" + os.path.basename(r.document)
            replies.append(item)
        return jsonify(replies=replies)

    @app.get("/api/books")
    def books():
        d = clock.now().date()
        m = bot().ledger.merchant(PHONE)
        rows = bot().ledger.day(PHONE, d)
        by = {}
        money_in = money_out = 0.0
        entries = []
        for r in rows:
            if r["direction"] == "in":
                by[r["provider"]] = by.get(r["provider"], 0) + r["amount"]
                money_in += r["amount"]
            else:
                money_out += r["amount"]
            entries.append({
                "time": r["occurred_at"][11:16], "channel": LABELS.get(r["provider"], r["provider"]),
                "who": r["counterparty"] or r["note"] or "", "ref": r["reference"] or "",
                "amount": r["amount"], "direction": r["direction"], "check": r["confidence"] == "check",
                "raw": r["raw"] or "",
            })
        return jsonify(
            consented=bool(m and m["consented"]),
            date=d.strftime("%a %d %b %Y"),
            totals={"in": money_in, "out": money_out, "cash": by.get("CASH", 0.0),
                    "digital": money_in - by.get("CASH", 0.0)},
            entries=list(reversed(entries)),
        )

    @app.get("/api/statement/<name>")
    def statement(name):
        path = os.path.join(pdf_dir, os.path.basename(name))
        if not name.endswith(".pdf") or not os.path.exists(path):
            abort(404)
        return send_file(path, mimetype="application/pdf")

    @app.post("/api/reset")
    def reset():
        bot().ledger.forget(PHONE)
        return jsonify(ok=True)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"\n  Kwacha Books is running. Open http://localhost:{port} in your browser.")
    print("  Press Ctrl+C here to stop.\n")
    create_app().run(host="127.0.0.1", port=port, debug=False)
