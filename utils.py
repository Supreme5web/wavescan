import re
import time
from datetime import datetime

_MD_SPECIAL = re.compile(r'([_*\[\]()~`>#+\-=|{}.!\\])')
_MC_RE = re.compile(r'^\$?([\d,]*\.?\d+)\s*([kKmMbB])?$')
CA_RE = re.compile(r'(0x[a-fA-F0-9]{40}|[1-9A-HJ-NP-Za-km-z]{32,44})')


def escape_md(text) -> str:
    """Escape text for Telegram MarkdownV2."""
    return _MD_SPECIAL.sub(r'\\\1', str(text))


def escape_url(url: str) -> str:
    """Escape a URL for use inside a MarkdownV2 [label](url) link."""
    return str(url).replace('\\', '\\\\').replace(')', '\\)')


def format_usd_short(value) -> str:
    if not value or value <= 0:
        return "N/A"
    if value < 1_000:
        return f"${value:.0f}"
    if value < 1_000_000:
        return f"${value / 1_000:.1f}K"
    return f"${value / 1_000_000:.2f}M"


def format_price(value) -> str:
    value = float(value or 0)
    return f"${value:.8f}" if 0 < value < 0.01 else f"${value:.4f}"


def truncate_ca(ca: str, n: int = 4) -> str:
    return f"{ca[:n]}...{ca[-n:]}" if ca and len(ca) > 2 * n else (ca or "")


def format_pct(value) -> str:
    return f"{float(value or 0):+.1f}%"


def format_age(created_ms) -> str:
    if not created_ms:
        return "N/A"
    diff_ms = time.time() * 1000 - created_ms
    days = diff_ms / 86_400_000
    if days >= 1:
        d = int(days)
        return f"{d} day{'s' if d != 1 else ''}"
    hours = diff_ms / 3_600_000
    if hours >= 1:
        return f"{hours:.0f}h"
    return f"{diff_ms / 60_000:.0f}m"


def risk_label(top10_pct: float):
    """(emoji, label) for a top-10 holder concentration percentage."""
    if top10_pct < 15:
        return "🟢", "Low Risk"
    if top10_pct < 30:
        return "⚠️", "Medium Risk"
    return "🔴", "High Risk"


def parse_mc(raw: str):
    """Parse '500k' / '1.2m' / '250000' into a float market-cap value."""
    if not raw:
        return None
    m = _MC_RE.match(raw.strip())
    if not m:
        return None
    num = float(m.group(1).replace(',', ''))
    mult = {'k': 1_000, 'm': 1_000_000, 'b': 1_000_000_000}.get((m.group(2) or '').lower(), 1)
    return num * mult


def find_ca(text: str):
    """Find the first plausible contract address in a block of text."""
    if not text:
        return None
    m = CA_RE.search(text)
    return m.group(0) if m else None


def parse_iso_ms(ts) -> int:
    """Parse a Postgres/Supabase timestamptz string into epoch milliseconds."""
    if not ts:
        return 0
    try:
        return int(datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return 0
