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

A single reading above the recorded ATH is deliberately NOT enough to
overwrite it. A thin-liquidity pool spiking on one trade, a bad API
sample, or Dexscreener/Solana Tracker briefly disagreeing can each
produce one inflated market-cap reading — and with no confirmation step,
that one bad sample would silently replace a real 43-day-old ATH with a
false one from moments ago (which is exactly the bug this fixes). So a
new high has to show up on two separate polls, within _CONFIRM_WINDOW_MS
of each other AND within _CONFIRM_TOLERANCE_PCT of the same value, before
it's accepted; a one-off spike that isn't corroborated by a similar
follow-up reading is discarded as noise. Once confirmed, the recorded
time is anchored to the FIRST sighting, not the confirming one, so the
age shown is accurate rather than lagging by a poll cycle.
"""
from datetime import datetime, timezone

import storage

# Minimum improvement over the current record to even be considered a
# candidate new high (filters out flat noise/rounding).
_MIN_DELTA_PCT = 0.005  # 0.5%

# A candidate has to be seen again, still above the record, within this
# many ms of its first sighting to be confirmed as a real new ATH.
_CONFIRM_WINDOW_MS = 5 * 60 * 1000  # 5 minutes

# The second sighting must also be within this much of the first
# sighting's value (not just independently above the old record) to
# confirm — otherwise two unrelated readings that both merely exceed the
# old baseline (e.g. a 50%-high glitch, followed by a later reading only
# 1% above baseline) would wrongly "confirm" each other at the glitch's
# inflated value.
_CONFIRM_TOLERANCE_PCT = 0.05  # 5%


def _key(ca: str) -> str:
    return f"ath:{ca}"


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def record_and_get(ca: str, candidate_mc: float):
    """Returns (ath_mc, ath_at_ms) — the confirmed best-known ATH and the
    epoch-ms timestamp it was first seen at (0 if unknown/not yet
    confirmed). Falls back to (candidate_mc, 0) if KV storage isn't
    configured.

    The very first time a token is seen, candidate_mc is seeded as the
    baseline but reported with no age — we don't know when that number
    was really hit (could've been hours or days before we started
    watching), so showing "just now" there would be misleading. Age is
    only reported once we've personally confirmed a ratchet past it.
    """
    candidate_mc = float(candidate_mc or 0)
    if not storage.available():
        return candidate_mc, 0

    existing = storage.get_json(_key(ca)) or {}
    best_mc = float(existing.get("mc") or 0)
    best_at = int(existing.get("at_ms") or 0)
    pending_mc = float(existing.get("pending_mc") or 0)
    pending_since = int(existing.get("pending_since_ms") or 0)
    now_ms = _now_ms()

    if best_mc <= 0:
        # First time we've ever seen this token — seed it, no age yet.
        storage.set_json(_key(ca), {"mc": candidate_mc, "at_ms": now_ms})
        return candidate_mc, 0

    threshold = best_mc * (1 + _MIN_DELTA_PCT)

    if candidate_mc > threshold:
        if (
            pending_mc > threshold
            and pending_since
            and (now_ms - pending_since) <= _CONFIRM_WINDOW_MS
            and candidate_mc >= pending_mc * (1 - _CONFIRM_TOLERANCE_PCT)
        ):
            # Second independent sighting above the record — confirmed.
            confirmed_mc = max(candidate_mc, pending_mc)
            storage.set_json(_key(ca), {"mc": confirmed_mc, "at_ms": pending_since})
            return confirmed_mc, pending_since

        # First sighting of this breakout — stage it, but do NOT overwrite
        # the record yet. The card keeps showing the old confirmed ATH
        # until a second poll agrees.
        storage.set_json(_key(ca), {
            "mc": best_mc,
            "at_ms": best_at,
            "pending_mc": candidate_mc,
            "pending_since_ms": now_ms,
        })
        return best_mc, best_at

    # Not above the record. Clear any stale pending candidate so a spike
    # that already reverted can't later "confirm" against an unrelated,
    # later spike.
    if pending_mc:
        storage.set_json(_key(ca), {"mc": best_mc, "at_ms": best_at})
    return best_mc, best_at
