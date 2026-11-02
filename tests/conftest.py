"""Tests run on SQLite by default. Set TEST_DATABASE_URL=postgresql://... to run them on PostgreSQL."""
import os

import pytest

from kwacha_books.ledger import Ledger


@pytest.fixture
def db_url(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        return str(tmp_path / "test.db")
    led = Ledger(url)
    for table in ("entries", "summary_log", "processed_messages", "merchants"):
        led._run(f"DELETE FROM {table}")
    return url
