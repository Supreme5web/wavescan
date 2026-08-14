"""Generate a crypto call-PNL card using assets/pnl_card_template.png.

The PNG template provides the complete background/UI artwork.
This module only draws the dynamic token logo, token name, metrics,
multiplier, and caller information on top of it.
"""

import io
import logging
import os
import tempfile
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# IMPORTANT: Render must have this file committed at:
#   assets/pnl_card_template.png
TEMPLATE_PATH = os.path.join(ASSETS_DIR, "pnl_card_template.png")

FONT_DIR = os.path.join(ASSETS_DIR, "fonts")
FONT_BOLD = os.path.join(FONT_DIR, "Rajdhani-Bold.ttf")
FONT_REGULAR = os.path.join(FONT_DIR, "Rajdhani-Medium.ttf")

WHITE = (255, 255, 255, 255)
LABEL_GRAY = (148, 168, 200, 255)
GREEN = (52, 211, 153, 255)
RED = (248, 113, 113, 255)
CYAN = (56, 189, 248, 255)

# Coordinates are based on the 1672x941 pnl_card_template artwork.
CONTENT_LEFT_F = 80 / 1672
COL2_X_F = 561 / 1672
CONTENT_RIGHT_F = 1592 / 1672

IDENTITY_TOP_F = 150 / 941
HEADER_BOTTOM_F = 227 / 941
DIVIDER_Y_F = 403 / 941
LABEL_TOP_F = 268 / 941
VALUE_TOP_F = 326 / 941
CAPTION_TOP_F = 441 / 941


def _font(path: str, size: int):
    return ImageFont.truetype(path, size)


def _fmt_compact(value) -> str:
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

    trimmed = text

    while trimmed and draw.textlength(trimmed + "…", font=font) > max_width:
        trimmed = trimmed[:-1]

    return trimmed + "…" if trimmed else "…"


def _fetch_logo(logo_url: Optional[str], size: int):
    if not logo_url:
        return None

    try:
        response = requests.get(logo_url, timeout=6)
        response.raise_for_status()

        logo = Image.open(
            io.BytesIO(response.content)
        ).convert("RGBA")

    except Exception as exc:
        logger.warning(
            "Could not fetch token logo from %s: %s",
            logo_url,
            exc,
        )
        return None

    logo = logo.resize(
        (size, size),
        Image.LANCZOS,
    )

    mask = Image.new(
        "L",
        (size, size),
        0,
    )

    ImageDraw.Draw(mask).ellipse(
        (0, 0, size, size),
        fill=255,
    )

    circular = Image.new(
        "RGBA",
        (size, size),
        (0, 0, 0, 0),
    )

    circular.paste(
        logo,
        (0, 0),
        mask,
    )

    return circular


def _draw_logo_placeholder(draw, box, symbol: str):
    x0, y0, x1, y1 = box

    draw.ellipse(
        box,
        fill=(20, 40, 80, 255),
        outline=CYAN,
        width=2,
    )

    letter = (symbol or "?")[0].upper()

    font = _font(
        FONT_BOLD,
        int((x1 - x0) * 0.55),
    )

    bbox = draw.textbbox(
        (0, 0),
        letter,
        font=font,
    )

    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]

    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2

    draw.text(
        (
            cx - w / 2 - bbox[0],
            cy - h / 2 - bbox[1],
        ),
        letter,
        font=font,
        fill=WHITE,
    )


def generate_pnl_card(call: dict) -> str:
    """Render a PNL card using assets/pnl_card_template.png.

    Required:
        token_name
        token_symbol
        entry_mc
        best_mc

    Optional:
        username
        logo_url
    """

    if not os.path.isfile(TEMPLATE_PATH):
        raise FileNotFoundError(
            f"PNL card template not found: {TEMPLATE_PATH}. "
            "Make sure pnl_card_template.png is committed inside the assets folder."
        )

    base = Image.open(
        TEMPLATE_PATH
    ).convert("RGBA")

    W, H = base.size

    overlay = Image.new(
        "RGBA",
        base.size,
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(overlay)

    entry_mc = float(call["entry_mc"])
    best_mc = float(call["best_mc"])

    mult = (
        best_mc / entry_mc
        if entry_mc
        else 0.0
    )

    accent = GREEN if mult >= 1 else RED

    content_left = int(W * CONTENT_LEFT_F)
    col2_x = int(W * COL2_X_F)
    content_right = int(W * CONTENT_RIGHT_F)

    identity_top = int(H * IDENTITY_TOP_F)
    header_bottom = int(H * HEADER_BOTTOM_F)
    divider_y = int(H * DIVIDER_Y_F)
    label_top = int(H * LABEL_TOP_F)
    value_top = int(H * VALUE_TOP_F)
    caption_top = int(H * CAPTION_TOP_F)

    logo_size = max(
        40,
        header_bottom - identity_top - 8,
    )

    # ---------------------------------------------------------------
    # Token logo
    # ---------------------------------------------------------------

    logo_box = (
        content_left,
        identity_top,
        content_left + logo_size,
        identity_top + logo_size,
    )

    logo_img = _fetch_logo(
        call.get("logo_url"),
        logo_size,
    )

    if logo_img is not None:
        overlay.paste(
            logo_img,
            (logo_box[0], logo_box[1]),
            logo_img,
        )

        draw.ellipse(
            logo_box,
            outline=CYAN,
            width=2,
        )
    else:
        _draw_logo_placeholder(
            draw,
            logo_box,
            call.get("token_symbol", "?"),
        )

    # ---------------------------------------------------------------
    # Token name
    # ---------------------------------------------------------------

    name_x = logo_box[2] + 14

    name_max_w = (
        col2_x
        - name_x
        - 20
    )

    name_text = (
        f"{call['token_name']} "
        f"(${call['token_symbol'].upper()})"
    )

    name_font = _fit_text(
        draw,
        name_text,
        FONT_BOLD,
        name_max_w,
        54,
    )

    name_display = _truncate_to_width(
        draw,
        name_text,
        name_font,
        name_max_w,
    )

    name_y = (
        logo_box[1]
        + (logo_size - name_font.size) / 2
        - 2
    )

    draw.text(
        (name_x, name_y),
        name_display,
        font=name_font,
        fill=WHITE,
    )

    # ---------------------------------------------------------------
    # Called At / Reached
    # ---------------------------------------------------------------

    label_font = _font(
        FONT_REGULAR,
        26,
    )

    value_font = _font(
        FONT_BOLD,
        56,
    )

    draw.text(
        (content_left, label_top),
        "CALLED AT",
        font=label_font,
        fill=LABEL_GRAY,
    )

    draw.text(
        (content_left, value_top),
        _fmt_compact(entry_mc),
        font=value_font,
        fill=WHITE,
    )

    draw.text(
        (col2_x, label_top),
        "REACHED",
        font=label_font,
        fill=LABEL_GRAY,
    )

    draw.text(
        (col2_x, value_top),
        _fmt_compact(best_mc),
        font=value_font,
        fill=accent,
    )

    # ---------------------------------------------------------------
    # Multiplier
    # ---------------------------------------------------------------

    mult_text = _fmt_mult(mult)

    mult_font = _fit_text(
        draw,
        mult_text,
        FONT_BOLD,
        content_right - col2_x - 260,
        150,
        min_size=60,
    )

    bbox = draw.textbbox(
        (0, 0),
        mult_text,
        font=mult_font,
    )

    mw = bbox[2] - bbox[0]
    mh = bbox[3] - bbox[1]

    mx = content_right - mw

    my = (
        (header_bottom + divider_y) / 2
        - mh / 2
        - bbox[1]
    )

    glow = Image.new(
        "RGBA",
        overlay.size,
        (0, 0, 0, 0),
    )

    ImageDraw.Draw(glow).text(
        (mx, my),
        mult_text,
        font=mult_font,
        fill=(*accent[:3], 90),
    )

    glow = glow.filter(
        ImageFilter.GaussianBlur(8)
    )

    overlay.alpha_composite(glow)

    draw = ImageDraw.Draw(overlay)

    draw.text(
        (mx, my),
        mult_text,
        font=mult_font,
        fill=accent,
    )

    # ---------------------------------------------------------------
    # Caller
    # ---------------------------------------------------------------

    username = call.get("username")

    if username:
        handle = (
            username
            if str(username).startswith("@")
            else f"@{username}"
        )

        caption_font = _font(
            FONT_BOLD,
            32,
        )

        draw.text(
            (content_left, caption_top),
            f"Called by {handle}",
            font=caption_font,
            fill=CYAN,
        )

    # ---------------------------------------------------------------
    # Save
    # ---------------------------------------------------------------

    final_img = Image.alpha_composite(
        base,
        overlay,
    ).convert("RGB")

    fd, path = tempfile.mkstemp(
        prefix="pnl_card_",
        suffix=".png",
        dir=tempfile.gettempdir(),
    )

    os.close(fd)

    final_img.save(
        path,
        "PNG",
    )

    return path