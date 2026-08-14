"""Solana Tracker market data for WaveScan."""

import solanatracker


def _pool_score(pool: dict) -> float:
    liquidity = pool.get("liquidity") or {}
    if isinstance(liquidity, dict):
        try:
            return float(liquidity.get("usd") or 0)
        except (TypeError, ValueError):
            pass
    return 0.0


def _number(value, default=0.0):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def fetch_best_pair(ca: str):
    """Fetch a token from Solana Tracker's /tokens/{tokenAddress} endpoint."""
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

    events = info.get("events") or {}
    event_1h = events.get("1h") or {}
    event_24h = events.get("24h") or {}
    change_1h = _number(event_1h.get("priceChangePercentage"))
    change_24h = _number(event_24h.get("priceChangePercentage"))

    # The /tokens endpoint provides identity/market/holder data. The stats
    # endpoint supplies exact timeframe trading stats such as 1h volume and
    # 1h buys/sells/transactions.
    stats = solanatracker.fetch_token_stats(ca)
    stats_1h = stats.get("1h") or {}
    stats_24h = stats.get("24h") or {}
    volume_1h = _number((stats_1h.get("volume") or {}).get("total") if isinstance(stats_1h.get("volume"), dict) else stats_1h.get("volume"))
    volume_24h = _number((stats_24h.get("volume") or {}).get("total") if isinstance(stats_24h.get("volume"), dict) else stats_24h.get("volume"))

    price_usd = _number(price.get("usd"))
    mc_usd = _number(market_cap.get("usd"))
    liquidity_usd = _number(liquidity.get("usd"))

    buys_1h = int(_number(stats_1h.get("buys")))
    sells_1h = int(_number(stats_1h.get("sells")))
    txns_1h = int(_number(stats_1h.get("transactions") or stats_1h.get("txns")))
    if not (buys_1h or sells_1h or txns_1h):
        # Keep a sensible fallback if the stats endpoint is temporarily empty.
        buys_1h = int(_number(info.get("buys")))
        sells_1h = int(_number(info.get("sells")))
        txns_1h = int(_number(info.get("txns")))
    holders = int(_number(info.get("holders")))

    creation = token.get("creation") or {}
    created_at = creation.get("created_time") or pool.get("createdAt")
    if created_at:
        created_at = int(_number(created_at))
        if created_at < 10_000_000_000:
            created_at *= 1000

    socials = []
    strict_socials = token.get("strictSocials") or {}
    for key, stype in (("twitter", "twitter"), ("telegram", "telegram"), ("discord", "discord")):
        url = strict_socials.get(key) or token.get(key)
        if url:
            socials.append({"type": stype, "url": url})

    websites = []
    website = token.get("website")
    if website:
        websites.append({"url": website})

    return {
        "chainId": "solana",
        "pairAddress": pool.get("poolId"),
        "pairCreatedAt": created_at,
        "baseToken": {
            "address": token.get("mint") or ca,
            "name": token.get("name") or "Unknown",
            "symbol": token.get("symbol") or "UNKNOWN",
        },
        "priceUsd": price_usd,
        "marketCap": mc_usd,
        "fdv": mc_usd,
        "liquidity": {"usd": liquidity_usd},
        "volume": {"h24": volume_24h, "h1": volume_1h},
        "priceChange": {"h24": change_24h, "h1": change_1h},
        "txns": {"h1": {"buys": buys_1h, "sells": sells_1h, "total": txns_1h}},
        "holders": holders,
        "info": {
            "imageUrl": token.get("image"),
            "socials": socials,
            "websites": websites,
        },
        "_solanaTracker": info,
    }


def get_market_cap(pair: dict) -> float:
    return _number(pair.get("marketCap") or pair.get("fdv"))


def get_ath_mc(pair: dict, current_mc: float) -> float:
    mint = (pair.get("baseToken") or {}).get("address")
    if mint and solanatracker.available():
        _, ath_mc = solanatracker.fetch_ath(mint)
        if ath_mc:
            return max(float(current_mc or 0), float(ath_mc))
    return float(current_mc or 0)
