from datetime import datetime, timezone

import requests

from config import DEXSCREENER_API, DEXPAPRIKA_API, DEXPAPRIKA_NETWORKS


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
    """Highest hourly 'high' on DexPaprika since an alert was created.

    A snapshot-only check ("is price above target right now?") misses a spike
    that already receded between two sweeps. Pulling OHLCV history and taking
    the max high since the alert was created catches that spike even if
    price has dropped back below target by the time we poll.
    """
    network = DEXPAPRIKA_NETWORKS.get(chain_id)
    if not network or not pool_address:
        return 0
    try:
        start = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        r = requests.get(
            f"{DEXPAPRIKA_API}/networks/{network}/pools/{pool_address}/ohlcv",
            params={"start": start, "interval": "1h"},
            timeout=10,
        )
        candles = r.json() or []
        highs = [c.get("high") for c in candles if c.get("high")]
        return max(highs) if highs else 0
    except Exception as err:
        print("fetch_peak_price failed:", err)
        return 0
