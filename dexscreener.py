"""
dexscreener.py
---------------
Solana Tracker (market.py) is the source of truth for price/liquidity/
volume/etc. It has no concept of a project banner though — that's a
Dexscreener-only feature, shown once a token has a real AMM pool (it
doesn't apply during the Pump.fun bonding-curve stage). This module does
exactly one thing: look up that banner image for a given mint, so bot.py
can prefer it over the plain token logo for migrated tokens.

Deliberately fails soft — any error just means "no banner", never an
exception that could break a /data reply.
"""

import requests

from config import DEXSCREENER_API


def fetch_banner(ca: str):
    """Returns the banner image URL for the highest-liquidity Dexscreener
    pair on this mint, or None if there isn't one / the lookup fails."""
    try:
        r = requests.get(f"{DEXSCREENER_API}/token-pairs/v1/solana/{ca}", timeout=4)
        r.raise_for_status()
        pairs = r.json() or []
        if not pairs:
            return None
        best = max(pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))
        return (best.get("info") or {}).get("header")
    except Exception as err:
        print(f"Dexscreener banner lookup failed for {ca}: {err}")
        return None
