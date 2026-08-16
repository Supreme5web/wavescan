"""Solana Tracker market-data adapter used by WaveScan."""

from datetime import datetime, timezone
import requests

from config import SOLANATRACKER_API, SOLANATRACKER_API_KEY
from solanatracker import fetch_ath


def _headers():
    return {"x-api-key": SOLANATRACKER_API_KEY}


def _get_json(url, params=None):
    r = requests.get(url, headers=_headers(), params=params or {}, timeout=10)
    r.raise_for_status()
    return r.json()


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
        pool_txns = pool.get("txns") or {}
        # Solana Tracker pool.txns can show up either flat ("volume1h") or
        # bucketed per-timeframe ("1h": {"volume": ...}) depending on
        # endpoint/version, so check both shapes before falling back.
        tf_1h = pool_txns.get("1h") if isinstance(pool_txns.get("1h"), dict) else {}
        vol1h = float(
            search.get("volume_1h")
            or pool_txns.get("volume1h")
            or tf_1h.get("volume")
            or tf_1h.get("volumeUsd")
            or 0
        )
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

        snipers = risk.get("snipers") or {}
        sniper_count = int(snipers.get("count") or 0)
        sniper_pct = float(snipers.get("totalPercentage") or 0)

        # NOTE: creator/dev fees-earned isn't confirmed in Solana Tracker's
        # public docs — trying the field names that would fit this payload
        # shape. Falls back to None (rendered as N/A) if none are present.
        fees_sol = None
        for src in (pool, token, risk, data):
            if not isinstance(src, dict):
                continue
            for key in ("creatorFeesSol", "creatorFees", "totalFeesSol", "feesSol", "fees"):
                val = src.get(key)
                if isinstance(val, dict):
                    val = val.get("sol") or val.get("total")
                if val is not None:
                    try:
                        fees_sol = float(val)
                        break
                    except (TypeError, ValueError):
                        continue
            if fees_sol is not None:
                break

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
            "dexPaid": bool(search.get("dexPaid") or data.get("dexPaid")),
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
