"""Builds real-time context for Hoody so it can answer token-specific,
market, and chat-history questions with live data instead of guessing."""

import re
from typing import Optional, Dict, Any

import requests

import market
import pnl_lookup
from config import SUPABASE_URL, SUPABASE_KEY, SOLANATRACKER_API, SOLANATRACKER_API_KEY
from utils import find_ca, format_usd_short, format_age, parse_iso_ms, CA_RE

# Keywords that signal the user wants recent/external info
_TREND_RE = re.compile(
    r'\b(news|trend|trending|lore|rumor|update|pump|dump|crash|moon|why|what happened|'
    r'recent|latest|announcement|partnership|hack|exploit|rug|dev\s+update|cto|'
    r'community|twitter|x\.com|bullish|bearish|sentiment|analysis|tech|technology|'
    r'whitepaper|roadmap|chart|buy|sell|should\s+i|is\s+it|do\s+you\s+think)\b',
    re.IGNORECASE,
)

# Memory / reference keywords — triggers chat-memory context
_MEMORY_RE = re.compile(
    r'\b(last|previous|recent|that|it|this one|the one|the coin|the token|'
    r'best coin|best call|who called|who dropped|who shared|first caller|'
    r'its ath|its mc|its price|how is it doing|hows it doing|my calls|'
    r'i dropped|i called|i shared)\b',
    re.IGNORECASE,
)

# Symbol pattern: $SYMBOL or standalone ALL CAPS word 2-10 chars
_SYMBOL_RE = re.compile(r'\$?([A-Z][A-Z0-9]{1,9})\b')

# Common words to ignore as symbols
_SYMBOL_BLOCKLIST = {
    "HOODY", "HELLO", "THANKS", "PLEASE", "SORRY", "GOOD", "GREAT", "NICE",
    "COOL", "PEAK", "BRUV", "FAM", "INNIT", "WAGWAN", "DEADASS", "TRAP",
    "BARE", "ENDS", "GOD", "YES", "NO", "OK", "LOL", "LMAO", "WTF", "OMG",
    "WASSUP", "SUP", "YO", "HEY", "HI", "BYE", "THE", "AND", "FOR", "YOU",
    "ARE", "WAS", "WERE", "BEEN", "HAVE", "HAS", "HAD", "DO", "DOES", "DID",
    "WILL", "WOULD", "COULD", "SHOULD", "MAY", "MIGHT", "CAN", "CANT",
    "IS", "IT", "ITS", "THIS", "THAT", "THESE", "THOSE", "MY", "YOUR",
    "HIS", "HER", "OUR", "THEIR", "ME", "HIM", "THEM", "US",
    "NOW", "THEN", "HERE", "THERE", "WHERE", "WHEN", "WHY", "HOW", "WHAT",
    "WHO", "WHICH", "WHOSE", "SOLANA", "ETHEREUM", "BITCOIN", "CRYPTO",
    "TOKEN", "COIN", "NFT", "DEFI", "DEX", "CEX", "ATH", "MC", "LP",
    "MARKET", "CAP", "PRICE", "VOLUME", "LIQUIDITY", "HOLDERS", "DEV",
    "RUG", "PUMP", "DUMP", "MOON", "BEAR", "BULL", "CHART", "TRADE",
    "TRADING", "BOT", "AI", "GEMINI", "GOOGLE", "SEARCH", "NEWS", "LORE",
    "TECH", "UPDATE", "SOON", "LATER", "TODAY", "TOMORROW", "YESTERDAY",
}


def _extract_ca_from_message(message: dict) -> Optional[str]:
    """Pull a contract address from a message's text (e.g. a bot token card)."""
    if not message:
        return None
    text = (message.get("text") or "").strip()
    if not text:
        return None
    return find_ca(text)


def _extract_symbols(text: str) -> list:
    """Find potential token symbols in text, excluding blocklist."""
    if not text:
        return []
    candidates = set()
    for m in _SYMBOL_RE.finditer(text):
        sym = m.group(1)
        if sym not in _SYMBOL_BLOCKLIST:
            candidates.add(sym)
    return list(candidates)


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


def _resolve_symbol(symbol: str) -> Optional[str]:
    """Look up a CA by symbol using Solana Tracker search."""
    try:
        if not SOLANATRACKER_API_KEY:
            return None
        r = requests.get(
            f"{SOLANATRACKER_API}/search",
            params={"query": symbol, "limit": 5, "format": "full"},
            headers={"x-api-key": SOLANATRACKER_API_KEY},
            timeout=6,
        )
        if not r.ok:
            return None
        data = r.json()
        rows = data.get("data") or []
        # Prefer exact symbol match
        for row in rows:
            mint = row.get("mint")
            if mint and CA_RE.fullmatch(mint):
                row_sym = (row.get("symbol") or "").upper()
                if row_sym == symbol.upper():
                    return mint
        # Fallback to first valid mint
        for row in rows:
            mint = row.get("mint")
            if mint and CA_RE.fullmatch(mint):
                return mint
        return None
    except Exception as err:
        print(f"[HOODY] symbol lookup failed for {symbol}: {err}")
        return None


def _format_call_row(row: dict) -> str:
    """Format a call row for the context prompt."""
    if not row:
        return "N/A"
    sym = (row.get("symbol") or "UNKNOWN").upper()
    ca = row.get("ca", "")
    entry = float(row.get("entry_mc") or 0)
    best = float(row.get("best_mc") or 0)
    mult = best / entry if entry else 0
    caller = row.get("username") or row.get("first_name") or "someone"
    called_at_ms = parse_iso_ms(row.get("called_at"))
    age = format_age(called_at_ms) if called_at_ms else "just now"
    ca_short = f"{ca[:4]}...{ca[-4:]}" if len(ca) > 8 else ca
    return f"${sym} ({ca_short}) — called by {caller} at {format_usd_short(entry)}, now {format_usd_short(best)} ({mult:.1f}x), {age} ago"


def _get_chat_memory(chat_id: int, user_id: int) -> Dict[str, Any]:
    """Fetch recent chat context from Supabase for memory-style questions."""
    memory = {
        "last_call": None,
        "best_call": None,
        "recent_calls": [],
        "user_calls": [],
    }
    if not (SUPABASE_URL and SUPABASE_KEY):
        return memory
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        }
        # Last call in this chat
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/calls",
            headers=headers,
            params={
                "chat_id": f"eq.{chat_id}",
                "select": "ca,symbol,entry_mc,best_mc,called_at,user_id,username,first_name",
                "order": "called_at.desc",
                "limit": 1,
            },
            timeout=6,
        )
        if r.ok:
            rows = r.json()
            if rows:
                memory["last_call"] = rows[0]
        # Best performing call in this chat
        r2 = requests.get(
            f"{SUPABASE_URL}/rest/v1/calls",
            headers=headers,
            params={
                "chat_id": f"eq.{chat_id}",
                "select": "ca,symbol,entry_mc,best_mc,called_at,user_id,username,first_name,multiple",
                "order": "multiple.desc",
                "limit": 1,
            },
            timeout=6,
        )
        if r2.ok:
            rows = r2.json()
            if rows:
                memory["best_call"] = rows[0]
        # Recent calls (last 5)
        r3 = requests.get(
            f"{SUPABASE_URL}/rest/v1/calls",
            headers=headers,
            params={
                "chat_id": f"eq.{chat_id}",
                "select": "ca,symbol,entry_mc,best_mc,called_at,user_id,username,first_name",
                "order": "called_at.desc",
                "limit": 5,
            },
            timeout=6,
        )
        if r3.ok:
            memory["recent_calls"] = r3.json()
        # User's own recent calls
        if user_id:
            r4 = requests.get(
                f"{SUPABASE_URL}/rest/v1/calls",
                headers=headers,
                params={
                    "chat_id": f"eq.{chat_id}",
                    "user_id": f"eq.{user_id}",
                    "select": "ca,symbol,entry_mc,best_mc,called_at",
                    "order": "called_at.desc",
                    "limit": 3,
                },
                timeout=6,
            )
            if r4.ok:
                memory["user_calls"] = r4.json()
    except Exception as err:
        print(f"[HOODY] chat memory query failed: {err}")
    return memory


def build_context(text: str, chat_id: int = None, reply_to_message: dict = None, user_id: int = None) -> str:
    """Build a context block to inject into Hoody's system prompt."""
    parts = []
    resolved_ca = None
    resolved_symbol = None

    # 1. Try to find CA in the current message text
    resolved_ca = find_ca(text)

    # 2. If no CA in text, check the replied-to message (e.g. bot token card)
    if not resolved_ca and reply_to_message:
        resolved_ca = _extract_ca_from_message(reply_to_message)
        if resolved_ca:
            parts.append("=== REFERENCED TOKEN (from replied message) ===")

    # 3. If still no CA, try symbol lookup from text
    if not resolved_ca:
        symbols = _extract_symbols(text)
        for sym in symbols:
            ca = _resolve_symbol(sym)
            if ca:
                resolved_ca = ca
                resolved_symbol = sym
                parts.append(f"=== RESOLVED SYMBOL ${sym} ===")
                break

    # 4. Fetch live token data for whatever CA we resolved
    token_summary = None
    if resolved_ca:
        token_summary = fetch_token_summary(resolved_ca)
        if token_summary:
            parts.append("=== LIVE TOKEN DATA ===")
            parts.append(token_summary)
            parts.append("")

    # 5. First-caller lookup for "who called it"
    if resolved_ca and chat_id and pnl_lookup.available():
        if any(phrase in text.lower() for phrase in ("who called", "first caller", "who dropped", "who shared")):
            first = pnl_lookup.get_first_call(chat_id, resolved_ca)
            if first:
                caller = first.get("username") or first.get("first_name") or "someone"
                entry = float(first.get("entry_mc") or 0)
                age = format_age(parse_iso_ms(first.get("called_at")))
                sym = (first.get("symbol") or "UNKNOWN").upper()
                parts.append("=== FIRST CALLER ===")
                parts.append(f"${sym} was first called by {caller} at {format_usd_short(entry)} ({age} ago)")
                parts.append("")

    # 6. Chat memory — for "last coin", "best coin", "my calls" etc.
    memory_triggered = bool(_MEMORY_RE.search(text)) or not resolved_ca
    if memory_triggered and chat_id:
        memory = _get_chat_memory(chat_id, user_id or 0)
        parts.append("=== CHAT MEMORY ===")

        if memory["last_call"]:
            parts.append(f"Last coin dropped in this chat: {_format_call_row(memory['last_call'])}")
        else:
            parts.append("Last coin dropped in this chat: none recorded")

        if memory["best_call"]:
            parts.append(f"Best performing call: {_format_call_row(memory['best_call'])}")
        else:
            parts.append("Best performing call: none recorded")

        if memory.get("user_calls"):
            parts.append("Your recent calls:")
            for row in memory["user_calls"]:
                parts.append(f"  • {_format_call_row(row)}")
        elif memory["recent_calls"]:
            parts.append("Recent calls in this chat:")
            for row in memory["recent_calls"][:3]:
                parts.append(f"  • {_format_call_row(row)}")

        parts.append("")

    # 7. Trend/news intent flag
    if _TREND_RE.search(text):
        parts.append("=== USER INTENT ===")
        parts.append(
            "The user is asking about recent events, trends, lore, "
            "market sentiment, or news. Use the most current data available. "
            "If you do not have real-time information, state that clearly."
        )
        parts.append("")

    return "\n".join(parts)
