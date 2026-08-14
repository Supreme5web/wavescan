from datetime import datetime, timezone

import requests

import solanatracker
from config import DEXSCREENER_API, DEXPAPRIKA_API, DEXPAPRIKA_NETWORKS


def get_market_cap(pair: dict) -> float:
    """FDV/marketCap from a Dexscreener pair, falling back to Solana
    Tracker for Solana tokens when Dexscreener hasn't populated either
    field yet. Without this fallback, callers that skip logging on a
    falsy market cap (leaderboard/PNL call-logging in particular) would
    silently drop a scan of a pair that's only seconds/minutes old."""
    mc = pair.get("fdv") or pair.get("marketCap") or 0
    if mc:
        return mc
    if pair.get("chainId") == "solana":
        mint = (pair.get("baseToken") or {}).get("address")
        if mint:
            return solanatracker.fetch_market_cap(mint)
    return mc


def get_ath_mc(pair: dict, current_mc: float) -> float:
    """All-time-high market cap for display. Solana tokens use Solana
    Tracker's dedicated /ath endpoint (computed from every indexed trade,
    so it can't miss a spike). Other chains, or Solana tokens if Solana
    Tracker isn't configured, fall back to the DexPaprika OHLCV lookback
    since the pool was created."""
    chain_id = pair.get("chainId")
    if chain_id == "solana" and solanatracker.available():
        mint = (pair.get("baseToken") or {}).get("address")
        if mint:
            _, ath_mc = solanatracker.fetch_ath(mint)
            if ath_mc:
                return max(current_mc, ath_mc)

    price = float(pair.get("priceUsd") or 0)
    pool = pair.get("pairAddress")
    created_ms = pair.get("pairCreatedAt")
    ath_mc = current_mc
    if price > 0 and current_mc > 0 and pool and created_ms:
        peak_price = fetch_peak_price(chain_id, pool, created_ms)
        if peak_price > 0:
            ath_mc = max(ath_mc, peak_price * (current_mc / price))
    return ath_mc


def fetch_best_pair(ca: str):
    """Highest-liquidity Dexscreener pair for a contract address, or None."""
    try:
        r = requests.get(f"{DEXSCREENER_API}/latest/dex/search", params={"q": ca}, timeout=10)
        pairs = (r.json() or {}).get("pairs") or []
        if not pairs:
            return None
        return max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
    except Exception as err:
        print("fetch_best_pair failed:", err)
        return None


def fetch_peak_price(chain_id: str, pool_address: str, since_ms: int) -> float:
    """Highest 'high' on DexPaprika since a token/alert was created.

    A snapshot-only check ("is price above target right now?") misses a spike
    that already receded between two sweeps. Pulling OHLCV history and taking
    the max high since creation catches that spike even if price has dropped
    back below target by the time we poll.

    Interval is chosen based on how old the pool is, not hardcoded to 1h:
    DexPaprika returns *empty* OHLCV for pools too new to have a closed
    candle at the requested granularity (their docs confirm this - "pool may
    be too new"), so a brand-new pump.fun launch (minutes old) would always
    come back with zero candles at 1h and silently look like "no ATH data",
    making ath_mc fall back to the live mc forever. Using 1m/5m for young
    pools ensures a candle actually exists to check.
    """
    network = DEXPAPRIKA_NETWORKS.get(chain_id)
    if not network or not pool_address:
        return 0

    age_ms = max(0, datetime.now(tz=timezone.utc).timestamp() * 1000 - since_ms)
    age_hours = age_ms / 3_600_000
    if age_hours <= 2:
        interval = "1m"
    elif age_hours <= 24:
        interval = "5m"
    elif age_hours <= 24 * 7:
        interval = "1h"
    else:
        interval = "24h"

    try:
        start = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        r = requests.get(
            f"{DEXPAPRIKA_API}/networks/{network}/pools/{pool_address}/ohlcv",
            params={"start": start, "interval": interval, "limit": 500},
            timeout=10,
        )
        candles = r.json() or []
        highs = [c.get("high") for c in candles if c.get("high")]
        return max(highs) if highs else 0
    except Exception as err:
        print("fetch_peak_price failed:", err)
        return 0
