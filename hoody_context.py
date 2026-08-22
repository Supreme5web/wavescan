"""Builds real-time context for Hoody so it can answer token-specific
and market questions with live data instead of guessing."""

import re
from typing import Optional

import market
from utils import find_ca, format_usd_short, format_age

# Keywords that signal the user wants recent/external info (news, lore, trends, etc.)
_TREND_RE = re.compile(
    r'\b(news|trend|trending|lore|rumor|update|pump|dump|crash|moon|why|what happened|'
    r'recent|latest|announcement|partnership|hack|exploit|rug|dev\s+update|cto|'
    r'community|twitter|x\.com|bullish|bearish|sentiment|analysis|tech|technology|'
    r'whitepaper|roadmap|chart|buy|sell|should\s+i|is\s+it|do\s+you\s+think)\b',
    re.IGNORECASE,
)


def fetch_token_summary(ca: str) -> Optional[str]:
    """Return a concise human-readable snapshot of a token's current stats."""
    pair = market.fetch_best_pair(ca)
    if not pair:
        return None

    base = pair.get("baseToken") or {}
    symbol = (base.get("symbol") or "UNKNOWN").upper()
    name = base.get("name") or symbol
    price = float(pair.get("priceUsd") or 0)
    mc = market.get_market_cap(pair)
    ath_mc = market.get_ath_mc(pair, mc)
    liq = float((pair.get("liquidity") or {}).get("usd") or 0)
    vol24 = float((pair.get("volume") or {}).get("h24") or 0)
    change24 = float((pair.get("priceChange") or {}).get("h24") or 0)
    age = format_age(pair.get("pairCreatedAt") or 0)
    dex = str(pair.get("dexId") or "unknown").replace("-", " ").title()
    holders = int(pair.get("holders") or 0)
    dev_pct = float(pair.get("devPercentage") or 0)
    dex_paid = "Yes" if pair.get("dexPaid") else "No"
    cto = "Yes" if pair.get("ctoApproved") else "No"

    # Pull social links if available
    socials = (pair.get("info") or {}).get("socials") or []
    social_lines = []
    for s in socials:
        t = s.get("type", "").lower()
        url = s.get("url", "")
        if url:
            label = "Twitter/X" if t in ("twitter", "x") else t.capitalize()
            social_lines.append(f"{label}: {url}")

    lines = [
        f"Token: {name} (${symbol})",
        f"Contract: {ca}",
        f"Price: ${price:.10f}" if price < 0.0001 else f"Price: ${price:.6f}" if price < 0.01 else f"Price: ${price:.4f}",
        f"Market Cap: {format_usd_short(mc)} | ATH: {format_usd_short(ath_mc)}",
        f"Liquidity: {format_usd_short(liq)} | 24h Volume: {format_usd_short(vol24)} ({change24:+.1f}%)",
        f"Age: {age} | DEX: {dex} | Holders: {holders:,}",
        f"Dev Holdings: {dev_pct:.1f}% | DEX Paid: {dex_paid} | CTO: {cto}",
    ]
    if social_lines:
        lines.append("Socials: " + " | ".join(social_lines))

    return "\n".join(lines)


def build_context(text: str) -> str:
    """Build a context block to inject into Hoody's system prompt."""
    parts = []

    # 1. Live token data when a CA is present
    ca = find_ca(text)
    if ca:
        summary = fetch_token_summary(ca)
        if summary:
            parts.append("=== LIVE TOKEN DATA ===")
            parts.append(summary)
            parts.append("")

    # 2. Intent flag for trend/news questions (guides the model to use
    #    search tools or be honest about its knowledge cutoff)
    if _TREND_RE.search(text):
        parts.append("=== USER INTENT ===")
        parts.append(
            "The user is asking about recent events, trends, lore, "
            "market sentiment, or news. Use the most current data available. "
            "If you do not have real-time information, state that clearly."
        )
        parts.append("")

    return "\n".join(parts)
