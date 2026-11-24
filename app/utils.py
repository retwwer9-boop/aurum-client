"""Время в Unix-секундах — одинаково работает в SQLite и Postgres."""

from __future__ import annotations

import time
from datetime import datetime, timezone


def now_ts() -> int:
    return int(time.time())


def iso(ts: int | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def days_left(expires_at: int | None) -> int:
    if not expires_at:
        return 0
    remaining = expires_at - now_ts()
    if remaining <= 0:
        return 0
    return remaining // 86400 + (1 if remaining % 86400 else 0)
