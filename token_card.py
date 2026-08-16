"""
token_card.py
-------------
Server-rendered token overlay, served via /card/<ca>/<nonce>.png (see
app.py) and embedded in Telegram messages as a link-preview image instead
of an uploaded sendPhoto (see bot.py's handle_data / refresh callback).

Deliberately kept fast and self-contained — no Solana RPC calls, only the
Dexscreener pair payload the caller already has — since Telegram's
link-preview scraper gives up quickly if the page is slow to respond.
"""

import io
import logging
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont

from pnl_card import FONT_BOLD, FONT_REGULAR
from utils import format_usd_short, format_price, format_age

logger = logging.getLogger(__name__)

# 1200x630 is the standard OG/link-preview size (~1.91:1) that Telegram's
# prefer_large_media renders as a big inline image.
WIDTH, HEIGHT = 1200, 630

BG = (5, 9, 16, 255)
WHITE = (255, 255, 255, 255)
GRAY = (148, 168, 200, 255)
CYAN = (56, 189, 248, 255)
GREEN = (52, 211, 153, 255)
RED = (248, 113, 113, 255)

LOGO_BOX = (56, 56, 216, 216)  # 160x160


def _font(path: str, size: int):
    return ImageFont.truetype(path, size)


def _fit_text(draw, text, font_path, max_width, start_size, min_size=18):
    size = start_size
    while size >= min_size:
        font = _font(font_path, size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 2
    return _font(font_path, min_size)


def _fetch_logo(logo_url: Optional[str], size: int):
    if not logo_url:
        return None
    try:
        r = requests.get(logo_url, timeout=3)
        r.raise_for_status()
        logo = Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception as exc:
        logger.warning("token_card: couldn't fetch logo %s: %s", logo_url, exc)
        return None

    logo.thumbnail((size - 8, size - 8), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - logo.width) // 2
    y = (size - logo.height) // 2
    canvas.alpha_composite(logo, (x, y))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(canvas, (0, 0), mask)
    return result


def _draw_logo(draw, overlay, symbol: str, logo_url: Optional[str]):
    x0, y0, x1, y1 = LOGO_BOX
    size = x1 - x0
    logo = _fetch_logo(logo_url, size)
    if logo:
        overlay.alpha_composite(logo, (x0, y0))
        draw.ellipse(LOGO_BOX, outline=CYAN, width=4)
        return

    draw.ellipse(LOGO_BOX, fill=(8, 15, 27, 255), outline=CYAN, width=4)
    letter = (symbol or "?")[0].upper()
    font = _font(FONT_BOLD, 72)
    bbox = draw.textbbox((0, 0), letter, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((x0 + x1 - w) / 2 - bbox[0], (y0 + y1 - h) / 2 - bbox[1]),
        letter, font=font, fill=WHITE,
    )


def _stat_cell(draw, x, y, w, label, value, value_color=WHITE):
    draw.text((x, y), label, font=_font(FONT_BOLD, 26), fill=CYAN)
    vf = _fit_text(draw, value, FONT_BOLD, w, 44, min_size=22)
    draw.text((x, y + 40), value, font=vf, fill=value_color)


def generate_token_card_bytes(pair: dict, ca: str) -> bytes:
    from market import get_market_cap, get_ath_mc  # local import: avoids a
    # circular import, since market.py doesn't need to know about this module

    base = pair.get("baseToken") or {}
    symbol = (base.get("symbol") or "UNKNOWN").upper()
    name = base.get("name") or symbol
    price = float(pair.get("priceUsd") or 0)
    mc = get_market_cap(pair)
    ath_mc = get_ath_mc(pair, mc)
    liq = float((pair.get("liquidity") or {}).get("usd") or 0)
    vol24 = float((pair.get("volume") or {}).get("h24") or 0)
    vol1h = float((pair.get("volume") or {}).get("h1") or 0)
    dex = str(pair.get("dexId") or "Unknown").replace("-", " ").title()
    created_ms = pair.get("pairCreatedAt") or 0
    age = format_age(created_ms)
    if age == "0m":
        age = "<1m"
    dev_pct = float(pair.get("devPercentage") or 0)
    dev_status = "HOLD" if dev_pct > 0 else "SOLD"
    dev_color = RED if dev_pct > 0 else GREEN
    logo_url = (pair.get("info") or {}).get("imageUrl")

    img = Image.new("RGBA", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((16, 16, WIDTH - 16, HEIGHT - 16), radius=28, outline=CYAN, width=3)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    _draw_logo(draw, overlay, symbol, logo_url)

    title = f"{name} (${symbol})"
    title_font = _fit_text(draw, title, FONT_BOLD, 760, 54, min_size=30)
    draw.text((240, 70), title, font=title_font, fill=WHITE)
    draw.text((240, 138), f"⌛ {age}  •  {dex}", font=_font(FONT_REGULAR, 30), fill=GRAY)

    # Dev badge, top-right
    badge_text = f"DEV {dev_status}"
    bf = _font(FONT_BOLD, 28)
    bbox = draw.textbbox((0, 0), badge_text, font=bf)
    bw, bh = bbox[2] - bbox[0] + 40, bbox[3] - bbox[1] + 24
    bx0, by0 = WIDTH - 56 - bw, 70
    draw.rounded_rectangle((bx0, by0, bx0 + bw, by0 + bh), radius=bh / 2, outline=dev_color, width=3)
    draw.text((bx0 + 20, by0 + 10), badge_text, font=bf, fill=dev_color)

    # Big MC figure
    draw.text((56, 260), "MARKET CAP", font=_font(FONT_BOLD, 30), fill=CYAN)
    mc_text = format_usd_short(mc)
    mc_font = _fit_text(draw, mc_text, FONT_BOLD, 520, 96, min_size=48)
    draw.text((56, 296), mc_text, font=mc_font, fill=WHITE)
    draw.text((56, 400), f"ATH {format_usd_short(ath_mc)}", font=_font(FONT_REGULAR, 30), fill=GRAY)

    # Bottom stat row
    cols = [
        ("PRICE", format_price(price), WHITE),
        ("LIQUIDITY", format_usd_short(liq), WHITE),
        ("VOL 24H", format_usd_short(vol24), WHITE),
        ("VOL 1H", format_usd_short(vol1h), WHITE),
    ]
    col_w = (WIDTH - 112) // 4
    for i, (label, value, color) in enumerate(cols):
        x = 56 + i * col_w
        _stat_cell(draw, x, 500, col_w - 24, label, value, color)

    final_img = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    final_img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
