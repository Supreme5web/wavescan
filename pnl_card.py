"""Generates a WaveScan call-PNL card image: shows the multiplier a called
token has done since it was first posted (entry mc) up to its peak (best
mc) tracked by the leaderboard, plus who called it.

Layout (on top of assets/pnl_card_template.png):
    [logo] TOKEN NAME                              12.4X   <- big, right side
           $SYMBOL
    ------------------------------------------------------
    CALLED AT              REACHED
    $5.00K                 $400.00K
    ------------------------------------------------------
                     Called by @username
"""

import io
import logging
import os
import tempfile
from typing import Optional

import httpx
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "assets", "pnl_card_template.png")

FONT_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")
FONT_BOLD = os.path.join(FONT_DIR, "Rajdhani-Bold.ttf")
FONT_REGULAR = os.path.join(FONT_DIR, "Rajdhani-Medium.ttf")

WHITE = (255, 255, 255, 255)
LABEL_GRAY = (148, 168, 200, 255)
GREEN = (52, 211, 153, 255)
RED = (248, 113, 113, 255)
CYAN = (56, 189, 248, 255)
DIVIDER_COLOR = (90, 120, 170, 130)

CONTENT_LEFT = 80
LOGO_SIZE = 120


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _fmt_compact(value) -> str:
    """$1.24M, $850.0K, $5.00K style formatting for market caps."""
    v = float(value or 0)
    if v >= 1_000_000_000:
        return f"${v / 1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"${v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v / 1_000:.2f}K"
    return f"${v:,.0f}"


def _fmt_mult(mult: float) -> str:
    if mult >= 100:
        return f"{mult:,.0f}X"
    if mult >= 10:
        return f"{mult:.1f}X"
    return f"{mult:.2f}X"


def _fit_text(draw, text, font_path, max_width, start_size, min_size=24):
    size = start_size
    while size > min_size:
        font = _font(font_path, size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 2
    return _font(font_path, min_size)


def _truncate_to_width(draw, text, font, max_width):
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    trimmed = text
    while trimmed and draw.textlength(trimmed + ellipsis, font=font) > max_width:
        trimmed = trimmed[:-1]
    return trimmed + ellipsis if trimmed else ellipsis


def _fetch_logo(logo_url: Optional[str], size: int) -> Optional[Image.Image]:
    if not logo_url:
        return None
    try:
        resp = httpx.get(logo_url, timeout=6)
        resp.raise_for_status()
        logo = Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except Exception as exc:  # noqa: BLE001 - logo is optional, never fail the card for it
        logger.warning("Could not fetch token logo from %s: %s", logo_url, exc)
        return None
    logo = logo.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    circular = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    circular.paste(logo, (0, 0), mask)
    return circular


def _draw_logo_placeholder(draw, box, symbol: str) -> None:
    x0, y0, x1, y1 = box
    draw.ellipse(box, fill=(20, 40, 80, 255), outline=CYAN, width=3)
    letter = (symbol or "?")[0].upper()
    font = _font(FONT_BOLD, int((x1 - x0) * 0.5))
    bbox = draw.textbbox((0, 0), letter, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    draw.text((cx - w / 2 - bbox[0], cy - h / 2 - bbox[1]), letter, font=font, fill=WHITE)


def _draw_accent_line(draw, x, y, width=32, thickness=3) -> None:
    glow_color = (CYAN[0], CYAN[1], CYAN[2], 70)
    draw.line((x, y, x + width, y), fill=glow_color, width=thickness + 4)
    draw.line((x, y, x + width, y), fill=CYAN, width=thickness)


def generate_pnl_card(call: dict) -> str:
    """Renders a call-PNL card PNG and returns the path to a temporary file.
    Caller is responsible for deleting the file after use.

    Expected keys in `call`:
        token_name, token_symbol, entry_mc, best_mc,
        username (optional - caller's @handle or first name),
        logo_url (optional)
    """
    base = Image.open(TEMPLATE_PATH).convert("RGBA")
    W, H = base.size
    content_right = int(W * 0.56)  # keep clear of the template's right-side art
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    entry_mc = float(call["entry_mc"])
    best_mc = float(call["best_mc"])
    mult = (best_mc / entry_mc) if entry_mc else 0.0
    accent = GREEN if mult >= 1 else RED

    # --- Token identity (logo + name/symbol), top-left ----------------------
    x = CONTENT_LEFT
    y = 90
    logo_box = (x, y, x + LOGO_SIZE, y + LOGO_SIZE)
    logo_img = _fetch_logo(call.get("logo_url"), LOGO_SIZE)
    if logo_img is not None:
        overlay.paste(logo_img, (x, y), logo_img)
        draw.ellipse(logo_box, outline=CYAN, width=3)
    else:
        _draw_logo_placeholder(draw, logo_box, call["token_symbol"])

    text_x = x + LOGO_SIZE + 24
    max_name_width = content_right - text_x
    name_font = _fit_text(draw, call["token_name"], FONT_BOLD, max_name_width, 58, min_size=32)
    name_display = _truncate_to_width(draw, call["token_name"], name_font, max_name_width)
    draw.text((text_x, y + 8), name_display, font=name_font, fill=WHITE)
    symbol_font = _font(FONT_REGULAR, 32)
    draw.text((text_x, y + 66), f"${call['token_symbol'].upper()}", font=symbol_font, fill=LABEL_GRAY)

    # --- Big multiplier, right side, vertically centered on the header ------
    mult_text = _fmt_mult(mult)
    mult_font = _fit_text(draw, mult_text, FONT_BOLD, W - content_right - 60, 150, min_size=70)
    mbbox = draw.textbbox((0, 0), mult_text, font=mult_font)
    mw, mh = mbbox[2] - mbbox[0], mbbox[3] - mbbox[1]
    mx = W - 70 - mw
    my = y + (LOGO_SIZE - mh) / 2 - mbbox[1]
    # subtle glow behind the multiplier for readability over busy art
    glow = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).text((mx, my), mult_text, font=mult_font, fill=(*accent[:3], 90))
    glow = glow.filter(__import__("PIL.ImageFilter", fromlist=["ImageFilter"]).GaussianBlur(8))
    overlay.alpha_composite(glow)
    draw.text((mx, my), mult_text, font=mult_font, fill=accent)

    # --- Divider --------------------------------------------------------------
    y += LOGO_SIZE + 44
    draw.line((x, y, W - 70, y), fill=DIVIDER_COLOR, width=2)

    # --- Called at / Reached row ----------------------------------------------
    y += 44
    label_font = _font(FONT_REGULAR, 32)
    value_font = _font(FONT_BOLD, 64)
    col2_x = x + int((content_right - x) * 0.55)

    draw.text((x, y), "CALLED AT", font=label_font, fill=LABEL_GRAY)
    _draw_accent_line(draw, x, y + label_font.size + 4)
    draw.text((x, y + 48), _fmt_compact(entry_mc), font=value_font, fill=WHITE)

    draw.text((col2_x, y), "REACHED", font=label_font, fill=LABEL_GRAY)
    _draw_accent_line(draw, col2_x, y + label_font.size + 4)
    draw.text((col2_x, y + 48), _fmt_compact(best_mc), font=value_font, fill=accent)

    # --- Divider below the stats ------------------------------------------
    y += 130
    draw.line((x, y, W - 70, y), fill=DIVIDER_COLOR, width=2)

    # --- Caller username, centered below the card content -------------------
    username = call.get("username")
    if username:
        handle = username if str(username).startswith("@") else f"@{username}"
        caller_text = f"Called by {handle}"
        uname_font = _font(FONT_BOLD, 36)
        text_w = draw.textlength(caller_text, font=uname_font)
        ux = (W - text_w) / 2
        uy = y + 26
        draw.text((ux, uy), caller_text, font=uname_font, fill=CYAN)

    # --- Composite + save -----------------------------------------------------
    final_img = Image.alpha_composite(base, overlay).convert("RGB")

    fd, path = tempfile.mkstemp(prefix="pnl_card_", suffix=".png", dir=tempfile.gettempdir())
    os.close(fd)
    final_img.save(path, "PNG")
    return path
