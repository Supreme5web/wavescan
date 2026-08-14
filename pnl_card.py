"""Generates a WaveScan call-PNL card image on top of the new
assets/pnl_card_template.png background (1672x941, WaveScan-branded, with a
divider baked into the art). Layout, top to bottom:

    [logo]TOKEN NAME ($SYM)              <- small identity row
    CALLED AT              REACHED   X.XXX  <- stats row + big multiplier
    ------------------------------------------------------  <- template art
    Called by @username
    [big WaveScan wordmark / chart art, baked into the template]
"""

import io
import logging
import os
import tempfile
from typing import Optional

import requests
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

# Layout fractions measured against the template's native 1672x941 art:
# header underline ~y=227, stats divider (baked into the template) ~y=407,
# "CALLED AT" column at x=80, "REACHED" column at x=561, content right edge
# ~x=1592. Expressed as fractions so the layout still holds if the template
# is ever swapped for a differently-sized version with the same proportions.
CONTENT_LEFT_F = 80 / 1672
COL2_X_F = 561 / 1672
CONTENT_RIGHT_F = 1592 / 1672
HEADER_BOTTOM_F = 227 / 941
DIVIDER_Y_F = 407 / 941
LABEL_TOP_F = 272 / 941
VALUE_TOP_F = 330 / 941
CAPTION_TOP_F = 445 / 941
LOGO_SIZE_F = 40 / 941


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _fmt_compact(value) -> str:
    """$1.24M, $850.00K, $5.00K style formatting for market caps."""
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


def _fit_text(draw, text, font_path, max_width, start_size, min_size=18):
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
        resp = requests.get(logo_url, timeout=6)
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
    draw.ellipse(box, fill=(20, 40, 80, 255), outline=CYAN, width=2)
    letter = (symbol or "?")[0].upper()
    font = _font(FONT_BOLD, int((x1 - x0) * 0.55))
    bbox = draw.textbbox((0, 0), letter, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    draw.text((cx - w / 2 - bbox[0], cy - h / 2 - bbox[1]), letter, font=font, fill=WHITE)


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
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    entry_mc = float(call["entry_mc"])
    best_mc = float(call["best_mc"])
    mult = (best_mc / entry_mc) if entry_mc else 0.0
    accent = GREEN if mult >= 1 else RED

    content_left = int(W * CONTENT_LEFT_F)
    col2_x = int(W * COL2_X_F)
    content_right = int(W * CONTENT_RIGHT_F)
    header_bottom = int(H * HEADER_BOTTOM_F)
    divider_y = int(H * DIVIDER_Y_F)
    label_top = int(H * LABEL_TOP_F)
    value_top = int(H * VALUE_TOP_F)
    caption_top = int(H * CAPTION_TOP_F)
    logo_size = max(28, int(H * LOGO_SIZE_F))

    # --- Token identity, small row in the gap above the stats ---------------
    logo_box = (content_left, header_bottom + 6, content_left + logo_size, header_bottom + 6 + logo_size)
    logo_img = _fetch_logo(call.get("logo_url"), logo_size)
    if logo_img is not None:
        overlay.paste(logo_img, (logo_box[0], logo_box[1]), logo_img)
        draw.ellipse(logo_box, outline=CYAN, width=2)
    else:
        _draw_logo_placeholder(draw, logo_box, call["token_symbol"])

    name_x = logo_box[2] + 14
    name_max_w = col2_x - name_x - 20
    name_text = f"{call['token_name']} (${call['token_symbol'].upper()})"
    name_font = _fit_text(draw, name_text, FONT_BOLD, name_max_w, 30)
    name_display = _truncate_to_width(draw, name_text, name_font, name_max_w)
    name_y = logo_box[1] + (logo_size - name_font.size) / 2 - 2
    draw.text((name_x, name_y), name_display, font=name_font, fill=WHITE)

    # --- CALLED AT / REACHED --------------------------------------------------
    label_font = _font(FONT_REGULAR, 26)
    value_font = _font(FONT_BOLD, 56)

    draw.text((content_left, label_top), "CALLED AT", font=label_font, fill=LABEL_GRAY)
    draw.text((content_left, value_top), _fmt_compact(entry_mc), font=value_font, fill=WHITE)

    draw.text((col2_x, label_top), "REACHED", font=label_font, fill=LABEL_GRAY)
    draw.text((col2_x, value_top), _fmt_compact(best_mc), font=value_font, fill=accent)

    # --- Big multiplier, right-aligned, vertically centered in the band ------
    mult_text = _fmt_mult(mult)
    mult_font = _fit_text(draw, mult_text, FONT_BOLD, content_right - col2_x - 260, 150, min_size=60)
    mbbox = draw.textbbox((0, 0), mult_text, font=mult_font)
    mw, mh = mbbox[2] - mbbox[0], mbbox[3] - mbbox[1]
    mx = content_right - mw
    my = (header_bottom + divider_y) / 2 - mh / 2 - mbbox[1]
    # subtle glow behind the multiplier for readability over busy art
    glow = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).text((mx, my), mult_text, font=mult_font, fill=(*accent[:3], 90))
    glow = glow.filter(__import__("PIL.ImageFilter", fromlist=["ImageFilter"]).GaussianBlur(8))
    overlay.alpha_composite(glow)
    draw.text((mx, my), mult_text, font=mult_font, fill=accent)

    # --- Caller, on the strip just below the template's divider --------------
    username = call.get("username")
    if username:
        handle = username if str(username).startswith("@") else f"@{username}"
        caption_font = _font(FONT_BOLD, 32)
        draw.text((content_left, caption_top), f"Called by {handle}", font=caption_font, fill=CYAN)

    # --- Composite + save -----------------------------------------------------
    final_img = Image.alpha_composite(base, overlay).convert("RGB")

    fd, path = tempfile.mkstemp(prefix="pnl_card_", suffix=".png", dir=tempfile.gettempdir())
    os.close(fd)
    final_img.save(path, "PNG")
    return path