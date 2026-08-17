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


def _best_pair(ca: str):
    """Highest-liquidity Dexscreener pair for this mint, or {} on failure."""
    r = requests.get(f"{DEXSCREENER_API}/token-pairs/v1/solana/{ca}", timeout=4)
    r.raise_for_status()
    pairs = r.json() or []
    if not pairs:
        return {}
    return max(pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))


def fetch_banner(ca: str):
    """Returns the banner image URL for the highest-liquidity Dexscreener
    pair on this mint, or None if there isn't one / the lookup fails."""
    try:
        best = _best_pair(ca)
        return (best.get("info") or {}).get("header")
    except Exception as err:
        print(f"Dexscreener banner lookup failed for {ca}: {err}")
        return None


def fetch_market_cap(ca: str) -> float:
    """Latest market cap (falls back to fdv) for this mint's highest-liquidity
    pair, straight from Dexscreener. Used for the 10s ATH refresher since it's
    much cheaper/faster to poll than Solana Tracker — returns 0.0 on any
    failure so callers can just skip a ratchet rather than crash."""
    try:
        best = _best_pair(ca)
        mc = float(best.get("marketCap") or best.get("fdv") or 0)
        return mc
    except Exception as err:
        print(f"Dexscreener market cap lookup failed for {ca}: {err}")
        return 0.0


def fetch_market_caps_batch(cas) -> dict:
    """Latest market cap (falls back to fdv) for each of `cas`, fetched in
    batches of up to 30 addresses per request via Dexscreener's tokens/v1
    endpoint — N single-token requests become ceil(N/30) requests.

    This exists specifically because calling fetch_market_cap() once per
    token in a loop (what sweep.py's fast_refresh_ath used to do) blows
    through Dexscreener's 300 req/min limit once there are more than a
    couple dozen actively-tracked tokens, since all of them get polled
    again every ~10s — every token in that loop was getting 429'd.

    Returns {ca: mc}. A ca missing from the result means its lookup
    failed, it wasn't found, or its market cap was 0 — same fail-soft
    pattern as fetch_market_cap, just batched.

    NOTE: Solana addresses are base58 and case-sensitive — never
    lowercase/uppercase them, unlike EVM hex addresses.
    """
    result = {}
    deduped = list(dict.fromkeys(c for c in cas if c))  # de-dupe, keep order
    for i in range(0, len(deduped), 30):
        chunk = deduped[i:i + 30]
        try:
            r = requests.get(
                f"{DEXSCREENER_API}/tokens/v1/solana/{','.join(chunk)}", timeout=8
            )
            r.raise_for_status()
            pairs = r.json() or []
        except Exception as err:
            print(f"Dexscreener batch market cap lookup failed for {len(chunk)} tokens: {err}")
            continue

        # A token can have multiple pools; keep the highest-liquidity one,
        # same tie-break _best_pair uses for the single-token lookup.
        best_liq = {}
        best_pair = {}
        for p in pairs:
            token_ca = (p.get("baseToken") or {}).get("address") or ""
            if not token_ca:
                continue
            liq = float((p.get("liquidity") or {}).get("usd") or 0)
            if token_ca not in best_liq or liq > best_liq[token_ca]:
                best_liq[token_ca] = liq
                best_pair[token_ca] = p

        for token_ca, p in best_pair.items():
            mc = float(p.get("marketCap") or p.get("fdv") or 0)
            if mc:
                result[token_ca] = mc

    return result
