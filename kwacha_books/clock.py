"""Local time for the merchants (Zambia by default), whatever timezone the server runs in."""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("BOT_TIMEZONE", "Africa/Lusaka"))


def now() -> datetime:
    """Current local time, without tzinfo (that's how times are stored)."""
    return datetime.now(TZ).replace(tzinfo=None)
