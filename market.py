"""Solana token market data for WaveScan.

All token/market data comes from Solana Tracker. No DexScreener or
DexPaprika requests are made here.
"""

import solanatracker


def _pool_score(pool: dict) -> float:
    liquidity = pool.get("liquidity") or {}
    if isinstance(liquidity, dict):
        return float(liquidity.get("usd") or 0)
    return 0.0


def _first_number(*values, default=0):
    for value in values:
        if value is None:
            continue
        try:
            number = float(value)
            if number:
                return number
        except (TypeError, ValueError):
            continue
    return default


def fetch_best_pair(ca: str):
    """Return a DexScreener-compatible normalized dict built from Solana Tracker."""
    info = solanatracker.fetch_token_info(ca)
    if not info:
        return None

    token = info.get("token") or {}
    pools = info.get("pools") or []
    if not pools:
        return None

    pool = max(pools, key=_pool_score)
    price = pool.get("price") or {}
    market_cap = pool.get("marketCap") or {}
    liquidity = pool.get("liquidity") or {}
    volume = pool.get("volume") or {}
    price_change = pool.get("priceChangePercentage") or pool.get("priceChange") or {}
    txns = pool.get("txns") or {}

    # Solana Tracker has used slightly different field names across API versions.
    price_usd = _first_number(
        price.get("usd") if isinstance(price, dict) else None,
        pool.get("priceUsd"),
    )
    mc_usd = _first_number(
        market_cap.get("usd") if isinstance(market_cap, dict) else market_cap,
        market_cap.get("value") if isinstance(market_cap, dict) else None,
        market_cap.get("marketCapUsd") if isinstance(market_cap, dict) else None,
        pool.get("marketCapUsd"),
        pool.get("marketCap"),
        token.get("marketCapUsd"),
        token.get("marketCap"),
        info.get("marketCapUsd"),
        info.get("marketCap"),
    )
    liquidity_usd = _first_number(
        liquidity.get("usd") if isinstance(liquidity, dict) else None,
        pool.get("liquidityUsd"),
    )

    vol_24h = _first_number(
        volume.get("24h") if isinstance(volume, dict) else None,
        volume.get("h24") if isinstance(volume, dict) else None,
        pool.get("volume24h"),
    )
    vol_1h = _first_number(
        volume.get("1h") if isinstance(volume, dict) else None,
        volume.get("h1") if isinstance(volume, dict) else None,
        pool.get("volume1h"),
    )
    change_24h = _first_number(
        price_change.get("24h") if isinstance(price_change, dict) else None,
        price_change.get("h24") if isinstance(price_change, dict) else None,
        pool.get("priceChange24h"),
    )

    txns_1h = txns.get("1h") or txns.get("h1") or {}
    if not isinstance(txns_1h, dict):
        txns_1h = {}

    created_at = pool.get("createdAt") or pool.get("created_at") or token.get("createdOn")
    if isinstance(created_at, str):
        # utils.format_age expects milliseconds; ISO timestamps are handled here.
        try:
            from datetime import datetime
            created_at = int(datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            created_at = None
    elif created_at:
        try:
            created_at = int(created_at)
            if created_at < 10_000_000_000:
                created_at *= 1000
        except (TypeError, ValueError):
            created_at = None

    socials = []
    for field, stype in (("twitter", "twitter"), ("telegram", "telegram"), ("discord", "discord")):
        url = token.get(field) or info.get(field)
        if url:
            socials.append({"type": stype, "url": url})

    websites = []
    website = token.get("website") or info.get("website")
    if website:
        websites.append({"url": website})

    image_url = token.get("image") or token.get("imageUrl") or info.get("image") or info.get("imageUrl")

    return {
        "chainId": "solana",
        "pairAddress": pool.get("poolId") or pool.get("address"),
        "pairCreatedAt": created_at,
        "baseToken": {
            "address": ca,
            "name": token.get("name") or info.get("name") or "Unknown",
            "symbol": token.get("symbol") or info.get("symbol") or "UNKNOWN",
        },
        "priceUsd": price_usd,
        "marketCap": mc_usd,
        "fdv": mc_usd,
        "liquidity": {"usd": liquidity_usd},
        "volume": {"h24": vol_24h, "h1": vol_1h},
        "priceChange": {"h24": change_24h},
        "txns": {"h1": {
            "buys": int(txns_1h.get("buys") or 0),
            "sells": int(txns_1h.get("sells") or 0),
        }},
        "info": {
            "imageUrl": image_url,
            "socials": socials,
            "websites": websites,
        },
        "_solanaTracker": info,
    }


def get_market_cap(pair: dict) -> float:
    """Return market cap from the normalized Solana Tracker response."""
    return float(pair.get("marketCap") or pair.get("fdv") or 0)


def get_ath_mc(pair: dict, current_mc: float) -> float:
    """Return Solana Tracker's indexed all-time-high market cap."""
    mint = (pair.get("baseToken") or {}).get("address")
    if mint and solanatracker.available():
        _, ath_mc = solanatracker.fetch_ath(mint)
        if ath_mc:
            return max(float(current_mc or 0), float(ath_mc))
    return float(current_mc or 0)
