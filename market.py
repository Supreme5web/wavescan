"""Solana Tracker market-data adapter used by WaveScan."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import requests

from config import (
    DEXPAPRIKA_API,
    DEXPAPRIKA_API_KEY,
    DEXPAPRIKA_NETWORKS,
    SOLANATRACKER_API,
    SOLANATRACKER_API_KEY,
)
from solanatracker import fetch_ath, fetch_token_stats


def _headers():
    return {"x-api-key": SOLANATRACKER_API_KEY}


def _dexpaprika_headers():
    """Attach the DexPaprika key if one is set; keyless requests (empty
    dict) still work, just against the lower shared quota. Confirmed via
    console.dexpaprika.com: the key goes in the Authorization header as-is
    (no Bearer/scheme prefix)."""
    return {"Authorization": DEXPAPRIKA_API_KEY} if DEXPAPRIKA_API_KEY else {}


def _get_json(url, params=None):
    r = requests.get(url, headers=_headers(), params=params or {}, timeout=10)
    r.raise_for_status()
    return r.json()


def _fetch_dex_orders(ca: str):
    """DexScreener's paid-orders ledger for a token — tokenProfile approval
    is the classic 'Dex Paid' checkmark; communityTakeover approval is a
    separate CTO signal. Response shape observed live is
    {"orders": [...], "boosts": [...]}, but tolerate a bare list too in
    case DexScreener reverts to the older shape."""
    try:
        r = requests.get(
            f"https://api.dexscreener.com/orders/v1/solana/{ca}", timeout=8
        )
        if not r.ok:
            return []
        data = r.json()
        if isinstance(data, list):
            return data
        return (data or {}).get("orders") or []
    except Exception as err:
        print("dexscreener orders fetch failed:", err)
        return []


def _first_pool(data: dict):
    pools = data.get("pools") or []
    if not pools:
        return {}
    return max(pools, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))


def _search_stats(ca: str):
    """Get the flat search representation because it exposes timeframe volumes."""
    try:
        data = _get_json(
            f"{SOLANATRACKER_API}/search",
            {"query": ca, "limit": 5, "format": "full", "showPriceChanges": "true"},
        )
        rows = data.get("data") or []
        for row in rows:
            if row.get("mint") == ca:
                return row
        return rows[0] if rows else {}
    except Exception as err:
        print(f"Solana Tracker search failed: {err}")
        return {}


def fetch_best_pair(ca: str):
    """Fetch and normalize one token from Solana Tracker's /tokens/{mint} endpoint.

    /tokens/{mint}, /search, /stats/{mint}, /tokens/{mint}/ath, and the
    Dexscreener orders lookup are all independent of each other — none of
    them need another's result as input — so they're fired concurrently
    instead of one after another. Run sequentially this was 5 network
    round-trips stacked back to back (the actual cause of /pnl and /data
    sometimes taking 10+ seconds); run in parallel it's bounded by the
    single slowest call instead of the sum of all five.
    """
    try:
        with ThreadPoolExecutor(max_workers=5) as executor:
            fut_primary = executor.submit(_get_json, f"{SOLANATRACKER_API}/tokens/{ca}")
            fut_search = executor.submit(_search_stats, ca)
            fut_stats = executor.submit(fetch_token_stats, ca)
            fut_ath = executor.submit(fetch_ath, ca)
            fut_orders = executor.submit(_fetch_dex_orders, ca)

            data = fut_primary.result()
            if not data or not data.get("token"):
                return None

            search = fut_search.result()
            stats = fut_stats.result()
            _, ath_from_endpoint = fut_ath.result()
            orders = fut_orders.result()

        token = data.get("token") or {}
        pool = _first_pool(data)
        events = data.get("events") or {}
        risk = data.get("risk") or {}
        creation = token.get("creation") or {}

        # /search gives timeframe volume and transaction fields while /tokens
        # supplies the detailed token/pool/risk/holder payload.
        vol24 = float(
            search.get("volume_24h")
            or (pool.get("txns") or {}).get("volume24h")
            or 0
        )
        # /tokens/{mint}'s pool.txns only carries cumulative "volume" and
        # "volume24h" — confirmed via a live sample, there's no 1h bucket
        # anywhere in that payload. /stats/{mint} is the endpoint actually
        # built for per-timeframe numbers, so that's what backs 1H here.
        # Schema unconfirmed beyond the top-level timeframe keys (mirrors
        # the "events" priceChangePercentage buckets already on /tokens),
        # so this checks a couple of plausible shapes for the volume value.
        vol1h = 0.0
        tf_stats = stats.get("1h") if isinstance(stats.get("1h"), dict) else {}
        if tf_stats:
            v = tf_stats.get("volume")
            if isinstance(v, dict):
                vol1h = float(v.get("total") or v.get("usd") or 0)
            else:
                vol1h = float(v or 0)
        if not vol1h:
            vol1h = float(search.get("volume_1h") or 0)
        buys1h = int(search.get("buys") or 0)
        sells1h = int(search.get("sells") or 0)

        # If search is unavailable, use the token endpoint's aggregate values.
        if not buys1h:
            buys1h = int(data.get("buys") or 0)
        if not sells1h:
            sells1h = int(data.get("sells") or 0)

        mc_values = [
            float((p.get("marketCap") or {}).get("usd") or 0)
            for p in (data.get("pools") or [])
        ]
        mc_values = [v for v in mc_values if v > 0]
        mc = float((pool.get("marketCap") or {}).get("usd") or 0)

        # /tokens/{mint} usually only has one active pool, so mc_values alone
        # just echoes the current market cap rather than a real peak. The
        # dedicated /ath endpoint tracks the true highest market cap across
        # every trade Solana Tracker has indexed for this token.
        ath_mc = max([mc, ath_from_endpoint] + mc_values)

        change24 = float((events.get("24h") or {}).get("priceChangePercentage") or 0)
        created_ms = int((creation.get("created_time") or 0) * 1000)
        if not created_ms:
            created_ms = int(pool.get("createdAt") or 0)

        socials = []
        strict = token.get("strictSocials") or {}
        for key, emoji_type in (("twitter", "twitter"), ("telegram", "telegram"), ("discord", "discord")):
            url = strict.get(key)
            if isinstance(url, str) and url:
                socials.append({"type": emoji_type, "url": url})
        if search.get("socials"):
            for key, url in (search.get("socials") or {}).items():
                if isinstance(url, str) and url and not any(s["type"] == key for s in socials):
                    socials.append({"type": key, "url": url})

        info = {
            "imageUrl": token.get("image"),
            "socials": socials,
            "websites": [],
        }

        # `orders` was already fetched concurrently above alongside search/stats/ath.
        dex_paid = any(
            o.get("type") == "tokenProfile" and o.get("status") == "approved"
            for o in orders
        )
        cto_approved = any(
            o.get("type") == "communityTakeover" and o.get("status") == "approved"
            for o in orders
        )

        snipers = risk.get("snipers") or {}
        sniper_count = int(snipers.get("count") or 0)
        sniper_pct = float(snipers.get("totalPercentage") or 0)

        # Confirmed from a live sample: risk.fees.total is the aggregate
        # SOL paid in trading + tip fees for this token across all
        # frontends/bots (helius-sender, jito, bloom, etc.), NOT a
        # creator-only figure.
        fees_sol = None
        fees_obj = risk.get("fees") or {}
        if isinstance(fees_obj, dict) and fees_obj.get("total") is not None:
            try:
                fees_sol = float(fees_obj["total"])
            except (TypeError, ValueError):
                fees_sol = None

        return {
            "chainId": "solana",
            "baseToken": {
                "address": token.get("mint") or ca,
                "name": token.get("name") or "Unknown",
                "symbol": token.get("symbol") or "UNKNOWN",
            },
            "priceUsd": float((pool.get("price") or {}).get("usd") or 0),
            "fdv": mc,
            "marketCap": mc,
            "athMc": ath_mc,
            "liquidity": {"usd": float((pool.get("liquidity") or {}).get("usd") or 0)},
            "volume": {"h24": vol24, "h1": vol1h},
            "priceChange": {"h24": change24},
            "txns": {"h1": {"buys": buys1h, "sells": sells1h}},
            "pairAddress": pool.get("poolId"),
            "pairCreatedAt": created_ms,
            "dexId": pool.get("market") or "unknown",
            "info": info,
            "events": events,
            "risk": risk,
            "holders": int(data.get("holders") or search.get("holders") or 0),
            "devPercentage": float((risk.get("dev") or {}).get("percentage") or search.get("dev") or 0),
            "devWallet": creation.get("creator") or search.get("deployer") or pool.get("deployer"),
            "dexPaid": dex_paid,
            "ctoApproved": cto_approved,
            "sniperCount": sniper_count,
            "sniperPercentage": sniper_pct,
            "feesSol": fees_sol,
        }
    except requests.HTTPError as err:
        print(f"Solana Tracker token lookup failed: {err}")
        return None
    except Exception as err:
        print(f"Solana Tracker token parse failed: {err}")
        return None


def get_market_cap(pair: dict) -> float:
    return float(pair.get("marketCap") or pair.get("fdv") or 0)


def get_ath_mc(pair: dict, current_mc: float) -> float:
    return max(float(current_mc or 0), float(pair.get("athMc") or 0))


# DexPaprika's accepted OHLCV intervals, in seconds — NOTE it's "24h", not
# "1d"; passing "1d" gets rejected with an error listing the valid values.
_OHLCV_INTERVALS_SECONDS = [
    ("1m", 60),
    ("5m", 300),
    ("10m", 600),
    ("15m", 900),
    ("30m", 1800),
    ("1h", 3600),
    ("6h", 21600),
    ("12h", 43200),
    ("24h", 86400),
]
# Cap how many candles we ask for in one request (no pagination here).
# DexPaprika rejects any limit above 366 with a 400 (confirmed live —
# their docs still advertise up to 500).
_MAX_CANDLES = 366


def _pick_ohlcv_interval(elapsed_seconds: float) -> str:
    """Finest granularity whose candle count for the elapsed window stays
    under _MAX_CANDLES — so a peak check on a call made 20 minutes ago gets
    1m candles (accurate), while one on a call made weeks ago falls back to
    daily candles instead of requesting thousands of rows in one call."""
    for label, secs in _OHLCV_INTERVALS_SECONDS:
        if elapsed_seconds / secs <= _MAX_CANDLES:
            return label
    return _OHLCV_INTERVALS_SECONDS[-1][0]


def _fetch_ohlcv_candles(network: str, pool_address: str, since_ms: int, until_ms: int = None):
    """Raw DexPaprika candles for [since_ms, until_ms] (until_ms defaults to
    now). Returns [] on any failure/empty result — never raises, so callers
    can fall back to another source.

    DexPaprika caps a single request to a 1-year span, so since_ms is
    clamped to at most ~364 days back; a token older than that will only
    get candles from within the last year (rare for the memecoin-heavy
    tokens this bot deals with, but worth knowing about).
    """
    if not network or not pool_address or not since_ms:
        return []

    now_ms = until_ms or int(time.time() * 1000)
    one_year_ms = 364 * 24 * 3600 * 1000
    since_ms = max(since_ms, now_ms - one_year_ms)

    elapsed_seconds = max((now_ms - since_ms) / 1000, 60)  # floor at 1 min
    interval = _pick_ohlcv_interval(elapsed_seconds)
    start = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    try:
        r = requests.get(
            f"{DEXPAPRIKA_API}/networks/{network}/pools/{pool_address}/ohlcv",
            params={"start": start, "interval": interval, "limit": _MAX_CANDLES},
            headers=_dexpaprika_headers(),
            timeout=8,
        )
        if not r.ok:
            print(f"DexPaprika OHLCV rejected: status={r.status_code} body={r.text[:300]!r}")
            return []
        return r.json() or []
    except Exception as err:
        print(f"DexPaprika OHLCV lookup failed for {pool_address}: {err}")
        return []


def fetch_peak_price(chain_id: str, pool_address: str, since_ms: int) -> float:
    """Highest `high` price DexPaprika has recorded for this pool since
    since_ms (epoch ms). Returns 0.0 if the chain has no DexPaprika network
    mapping (see config.DEXPAPRIKA_NETWORKS), the pool is too new to have
    any candles yet, or the lookup fails.

    No API key needed — DexPaprika's pool OHLCV endpoint is public.
    """
    network = DEXPAPRIKA_NETWORKS.get(chain_id)
    candles = _fetch_ohlcv_candles(network, pool_address, since_ms)
    if not candles:
        return 0.0
    return max(float(c.get("high") or 0) for c in candles)


def fetch_ath_from_ohlcv(
    chain_id: str, pool_address: str, since_ms: int, current_price: float, current_mc: float
):
    """The token's real all-time-high market cap AND when it actually
    happened, read straight from DexPaprika's historical candles — not
    inferred from whenever the bot happened to be polling. Returns
    (ath_mc, ath_at_ms), or (0.0, 0) if it can't be determined (unsupported
    chain, pool too new, current_price missing, or the lookup fails), so
    callers should fall back to get_ath_mc()'s floor in that case.

    OHLCV gives price, not market cap, so this converts using the
    price -> mc ratio implied by the live pair (mc = price * supply, and
    that ratio is assumed constant — true for the fixed-supply memecoins
    this bot mostly deals with, since Pump.fun-style launches mint the
    full supply upfront and don't mint/burn afterward).
    """
    network = DEXPAPRIKA_NETWORKS.get(chain_id)
    current_price = float(current_price or 0)
    current_mc = float(current_mc or 0)
    if not network or not pool_address or not since_ms or current_price <= 0:
        return 0.0, 0

    candles = _fetch_ohlcv_candles(network, pool_address, since_ms)
    if not candles:
        return 0.0, 0

    peak_candle = max(candles, key=lambda c: float(c.get("high") or 0))
    peak_price = float(peak_candle.get("high") or 0)
    if peak_price <= 0:
        return 0.0, 0

    supply = current_mc / current_price if current_price > 0 else 0
    candle_ath_mc = peak_price * supply

    time_open = peak_candle.get("time_open")
    try:
        candle_at_ms = int(
            datetime.fromisoformat(str(time_open).replace("Z", "+00:00")).timestamp() * 1000
        )
    except (TypeError, ValueError):
        candle_at_ms = 0

    # Live price can already be past the last completed candle (DexPaprika
    # candles lag slightly behind real-time), so never report an ATH below
    # what's happening right now — if the current mc is actually the
    # highest we know about, the ATH is "now".
    if current_mc >= candle_ath_mc:
        return current_mc, int(time.time() * 1000)

    return candle_ath_mc, candle_at_ms
