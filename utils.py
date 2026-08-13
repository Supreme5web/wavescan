import re

_MD_SPECIAL = re.compile(r'([_*\[\]()~`>#+\-=|{}.!\\])')
_MC_RE = re.compile(r'^\$?([\d,]*\.?\d+)\s*([kKmMbB])?$')
CA_RE = re.compile(r'(0x[a-fA-F0-9]{40}|[1-9A-HJ-NP-Za-km-z]{32,44})')


def escape_md(text) -> str:
    """Escape text for Telegram MarkdownV2."""
    return _MD_SPECIAL.sub(r'\\\1', str(text))


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
