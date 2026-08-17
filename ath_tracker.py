"""Tracks each token's own all-time-high market cap *and when it was hit*.

Neither Solana Tracker's `/tokens/{mint}/ath` response nor a Dexscreener
pair exposes a confirmed "when" field for the peak, so instead of guessing
at an unconfirmed schema, this just watches every market-cap figure that
already flows through the bot and remembers the highest one it's ever
seen per mint, with our own timestamp. Backed by the same Upstash KV store
as storage.py.

Fed from two places, so actively-called tokens get an accurate ATH age
even between manual refreshes:
  - bot.py, every time a pair is fetched for /data or the Refresh button
  - sweep.py's fast_refresh_ath(), the 10s Dexscreener background loop
"""
from datetime import datetime, timezone

import storage


def _key(ca: str) -> str:
    return f"ath:{ca}"


def record_and_get(ca: str, candidate_mc: float):
    """Ratchets the stored ATH for `ca` up to candidate_mc if it's a new
    high, and returns (ath_mc, ath_at_ms) — the best known ATH and the
    epoch-ms timestamp it was hit at (0 if unknown).

    Falls back to (candidate_mc, 0) if KV storage isn't configured, so the
    card still shows a number, just without an age next to it.
    """
    candidate_mc = float(candidate_mc or 0)
    if not storage.available():
        return candidate_mc, 0

    existing = storage.get_json(_key(ca)) or {}
    best_mc = float(existing.get("mc") or 0)
    best_at = int(existing.get("at_ms") or 0)

    if candidate_mc > best_mc:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        storage.set_json(_key(ca), {"mc": candidate_mc, "at_ms": now_ms})
        return candidate_mc, now_ms

    if best_mc > 0:
        return best_mc, best_at
    return candidate_mc, 0
