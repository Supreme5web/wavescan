"""Looks up the first person to call a given contract address in a chat, for
the /pnl <ca> command. Queries the same `calls` table leaderboard.py writes
to (see README.md's create table statement), but read-only and independent
of leaderboard.py's internals so this drops in without touching that file.
"""

import logging

import requests

from config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)


def available() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def get_first_call(chat_id, ca: str) -> dict | None:
    """Returns the earliest-called row for (chat_id, ca), or None if nobody
    in this chat has called it (or Supabase isn't configured / errors)."""
    if not available():
        return None
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/calls",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
            },
            params={
                "chat_id": f"eq.{chat_id}",
                "ca": f"eq.{ca}",
                "order": "called_at.asc",
                "limit": 1,
            },
            timeout=10,
        )
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001 - lookup is best-effort
        logger.warning("get_first_call failed for chat=%s ca=%s: %s", chat_id, ca, exc)
        return None
