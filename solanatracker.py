"""Solana Tracker Data API helpers.

Used for two things Dexscreener + DexPaprika can't reliably give us for
Solana tokens:

1. A real all-time-high. Solana Tracker keeps a running ATH computed from
   every trade it has indexed for a token, so `/tokens/{mint}/ath` doesn't
   miss a spike the way a coarse OHLCV candle lookback (DexPaprika) can,
   especially on very young pools where only 1m/5m candles exist for a
   short window.
2. A fallback market cap. Dexscreener's `/latest/dex/search` frequently
   returns pairs with no `fdv`/`marketCap` at all in the first seconds/
   minutes after a pool is created — Solana Tracker's `/tokens/{mint}`
   response has a populated `marketCap` on its primary pool sooner.

Both functions degrade to falsy return values on any failure/missing key,
same pattern as the rest of this codebase, so callers can always fall back.
"""
import requests

from config import SOLANATRACKER_API, SOLANATRACKER_API_KEY

_TIMEOUT = 10


def available() -> bool:
    return bool(SOLANATRACKER_API_KEY)


def _headers() -> dict:
    return {"x-api-key": SOLANATRACKER_API_KEY}


def fetch_token_info(mint: str):
    """Full token payload (pools, holders, risk score, etc.) or None."""
    if not available() or not mint:
        return None
    try:
        r = requests.get(f"{SOLANATRACKER_API}/tokens/{mint}", headers=_headers(), timeout=_TIMEOUT)
        if not r.ok:
            return None
        return r.json()
    except Exception as err:
        print("solanatracker fetch_token_info failed:", err)
        return None


def fetch_market_cap(mint: str) -> float:
    """Market cap (USD) from the token's primary pool, or 0."""
    info = fetch_token_info(mint)
    pools = (info or {}).get("pools") or []
    if not pools:
        return 0
    mc = (pools[0].get("marketCap") or {}).get("usd")
    return float(mc or 0)


def fetch_ath(mint: str):
    """(ath_price, ath_market_cap) since Solana Tracker started recording
    this token, or (0, 0) on failure/unavailable/not-yet-indexed."""
    if not available() or not mint:
        return 0, 0
    try:
        r = requests.get(f"{SOLANATRACKER_API}/tokens/{mint}/ath", headers=_headers(), timeout=_TIMEOUT)
        if not r.ok:
            return 0, 0
        data = r.json() or {}
        return float(data.get("highest_price") or 0), float(data.get("highest_market_cap") or 0)
    except Exception as err:
        print("solanatracker fetch_ath failed:", err)
        return 0, 0
