"""Solana Tracker market-data adapter used by WaveScan."""

from datetime import datetime, timezone
import requests

from config import SOLANATRACKER_API, SOLANATRACKER_API_KEY
from solanatracker import fetch_ath, fetch_token_stats


def _headers():
    return {"x-api-key": SOLANATRACKER_API_KEY}


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
    """Fetch and normalize one token from Solana Tracker's /tokens/{mint} endpoint."""
    try:
        data = _get_json(f"{SOLANATRACKER_API}/tokens/{ca}")
        if not data or not data.get("token"):
            return None

        token = data.get("token") or {}
        pool = _first_pool(data)
        search = _search_stats(ca)
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
        stats = fetch_token_stats(ca)
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
        _, ath_from_endpoint = fetch_ath(ca)
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

        orders = _fetch_dex_orders(ca)
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


def fetch_peak_price(chain_id: str, pool_address: str, since_ms: int) -> float:
    return 0.0
