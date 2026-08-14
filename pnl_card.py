"""Generate a futuristic crypto call-PNL card.

Designed for the 1672x941 WaveScan-style background:
    assets/pnl_card_template.png

Layout:
    - Large token logo at the top-left
    - Large token name/symbol beside the logo
    - CALLED AT / REACHED / multiplier stats below
    - Optional "Called by @username" caption below the divider
"""

import io
import logging
import os
import tempfile
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)

TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__),
    "assets",
    "pnl_card_template.png",
)

FONT_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")
FONT_BOLD = os.path.join(FONT_DIR, "Rajdhani-Bold.ttf")
FONT_REGULAR = os.path.join(FONT_DIR, "Rajdhani-Medium.ttf")

WHITE = (255, 255, 255, 255)
LABEL_GRAY = (148, 168, 200, 255)
GREEN = (52, 211, 153, 255)
RED = (248, 113, 113, 255)
CYAN = (56, 189, 248, 255)

# ---------------------------------------------------------------------------
# Layout for the 1672x941 background
# ---------------------------------------------------------------------------

# Large identity section.
LOGO_LEFT_F = 55 / 1672
LOGO_TOP_F = 48 / 941
LOGO_SIZE_F = 245 / 941

NAME_LEFT_F = 325 / 1672
NAME_TOP_F = 102 / 941
NAME_RIGHT_F = 1120 / 1672

# Stats section.
STATS_LEFT_F = 325 / 1672
COL2_X_F = 710 / 1672
CONTENT_RIGHT_F = 1580 / 1672

LABEL_TOP_F = 278 / 941
VALUE_TOP_F = 326 / 941

# Divider/caption area.
DIVIDER_Y_F = 407 / 941
CAPTION_LEFT_F = 65 / 1672
CAPTION_TOP_F = 438 / 941


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _fmt_compact(value) -> str:
    """Format market caps as $1.24M, $850.00K, etc."""
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


def _fit_text(
    draw,
    text: str,
    font_path: str,
    max_width: int,
    start_size: int,
    min_size: int = 18,
):
    size = start_size

    while size > min_size:
        font = _font(font_path, size)

        if draw.textlength(text, font=font) <= max_width:
            return font

        size -= 2

    return _font(font_path, min_size)


def _truncate_to_width(draw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text

    ellipsis = "…"
    trimmed = text

    while trimmed and draw.textlength(
        trimmed + ellipsis,
        font=font,
    ) > max_width:
        trimmed = trimmed[:-1]

    return trimmed + ellipsis if trimmed else ellipsis


def _fetch_logo(
    logo_url: Optional[str],
    size: int,
) -> Optional[Image.Image]:
    """Download and crop the token logo into a circular image."""
    if not logo_url:
        return None

    try:
        resp = requests.get(logo_url, timeout=6)
        resp.raise_for_status()

        logo = Image.open(
            io.BytesIO(resp.content)
        ).convert("RGBA")

    except Exception as exc:  # noqa: BLE001
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


def _draw_logo_placeholder(
    draw,
    box,
    symbol: str,
) -> None:
    """Fallback token logo when logo_url is unavailable."""
    x0, y0, x1, y1 = box

    draw.ellipse(
        box,
        fill=(8, 20, 45, 255),
        outline=CYAN,
        width=5,
    )

    letter = (symbol or "?")[0].upper()

    font = _font(
        FONT_BOLD,
        int((x1 - x0) * 0.50),
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


def _draw_glowing_logo_border(
    overlay: Image.Image,
    box,
) -> None:
    """Add the neon-blue ring around the large token logo."""
    glow = Image.new(
        "RGBA",
        overlay.size,
        (0, 0, 0, 0),
    )

    glow_draw = ImageDraw.Draw(glow)

    glow_draw.ellipse(
        box,
        outline=(*CYAN[:3], 180),
        width=10,
    )

    glow = glow.filter(
        ImageFilter.GaussianBlur(12)
    )

    overlay.alpha_composite(glow)

    draw = ImageDraw.Draw(overlay)

    draw.ellipse(
        box,
        outline=CYAN,
        width=5,
    )


def generate_pnl_card(call: dict) -> str:
    """Render a call-PNL card and return its temporary PNG path.

    Expected keys in `call`:
        token_name
        token_symbol
        entry_mc
        best_mc

    Optional:
        username
        logo_url
    """

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

    # -----------------------------------------------------------------------
    # Values
    # -----------------------------------------------------------------------

    entry_mc = float(call["entry_mc"])
    best_mc = float(call["best_mc"])

    mult = (
        best_mc / entry_mc
        if entry_mc
        else 0.0
    )

    accent = (
        GREEN
        if mult >= 1
        else RED
    )

    # -----------------------------------------------------------------------
    # Coordinates
    # -----------------------------------------------------------------------

    logo_left = int(W * LOGO_LEFT_F)
    logo_top = int(H * LOGO_TOP_F)
    logo_size = int(H * LOGO_SIZE_F)

    name_left = int(W * NAME_LEFT_F)
    name_top = int(H * NAME_TOP_F)
    name_right = int(W * NAME_RIGHT_F)

    stats_left = int(W * STATS_LEFT_F)
    col2_x = int(W * COL2_X_F)
    content_right = int(W * CONTENT_RIGHT_F)

    label_top = int(H * LABEL_TOP_F)
    value_top = int(H * VALUE_TOP_F)

    divider_y = int(H * DIVIDER_Y_F)

    caption_left = int(W * CAPTION_LEFT_F)
    caption_top = int(H * CAPTION_TOP_F)

    # -----------------------------------------------------------------------
    # Large token logo — top-left
    # -----------------------------------------------------------------------

    logo_box = (
        logo_left,
        logo_top,
        logo_left + logo_size,
        logo_top + logo_size,
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

        _draw_glowing_logo_border(
            overlay,
            logo_box,
        )

    else:
        _draw_logo_placeholder(
            draw,
            logo_box,
            call["token_symbol"],
        )

    # -----------------------------------------------------------------------
    # Large token name beside logo
    # -----------------------------------------------------------------------

    name_text = (
        f"{call['token_name']} "
        f"(${call['token_symbol'].upper()})"
    )

    name_max_width = (
        name_right
        - name_left
    )

    name_font = _fit_text(
        draw,
        name_text,
        FONT_BOLD,
        name_max_width,
        start_size=92,
        min_size=46,
    )

    name_display = _truncate_to_width(
        draw,
        name_text,
        name_font,
        name_max_width,
    )

    name_bbox = draw.textbbox(
        (0, 0),
        name_display,
        font=name_font,
    )

    name_height = (
        name_bbox[3]
        - name_bbox[1]
    )

    # Vertically center the title against the logo.
    name_y = (
        logo_top
        + (logo_size - name_height) / 2
        - name_bbox[1]
    )

    # Soft blue glow behind the token name.
    name_glow = Image.new(
        "RGBA",
        overlay.size,
        (0, 0, 0, 0),
    )

    ImageDraw.Draw(name_glow).text(
        (name_left, name_y),
        name_display,
        font=name_font,
        fill=(56, 189, 248, 75),
    )

    name_glow = name_glow.filter(
        ImageFilter.GaussianBlur(7)
    )

    overlay.alpha_composite(name_glow)

    draw = ImageDraw.Draw(overlay)

    draw.text(
        (name_left, name_y),
        name_display,
        font=name_font,
        fill=WHITE,
    )

    # -----------------------------------------------------------------------
    # CALLED AT / REACHED
    # -----------------------------------------------------------------------

    label_font = _font(
        FONT_REGULAR,
        28,
    )

    value_font = _font(
        FONT_BOLD,
        60,
    )

    draw.text(
        (stats_left, label_top),
        "CALLED AT",
        font=label_font,
        fill=LABEL_GRAY,
    )

    draw.text(
        (stats_left, value_top),
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

    # -----------------------------------------------------------------------
    # Large multiplier
    # -----------------------------------------------------------------------

    mult_text = _fmt_mult(mult)

    mult_max_width = (
        content_right
        - col2_x
        - 40
    )

    mult_font = _fit_text(
        draw,
        mult_text,
        FONT_BOLD,
        mult_max_width,
        start_size=150,
        min_size=70,
    )

    mbbox = draw.textbbox(
        (0, 0),
        mult_text,
        font=mult_font,
    )

    mw = mbbox[2] - mbbox[0]
    mh = mbbox[3] - mbbox[1]

    mx = content_right - mw

    # Keep multiplier vertically centered in the stats band.
    my = (
        (divider_y + label_top) / 2
        - mh / 2
        - mbbox[1]
        + 42
    )

    # Neon glow.
    glow = Image.new(
        "RGBA",
        overlay.size,
        (0, 0, 0, 0),
    )

    ImageDraw.Draw(glow).text(
        (mx, my),
        mult_text,
        font=mult_font,
        fill=(*accent[:3], 95),
    )

    glow = glow.filter(
        ImageFilter.GaussianBlur(10)
    )

    overlay.alpha_composite(glow)

    draw = ImageDraw.Draw(overlay)

    draw.text(
        (mx, my),
        mult_text,
        font=mult_font,
        fill=accent,
    )

    # -----------------------------------------------------------------------
    # Optional caller caption
    # -----------------------------------------------------------------------

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
            (caption_left, caption_top),
            f"Called by {handle}",
            font=caption_font,
            fill=CYAN,
        )

    # -----------------------------------------------------------------------
    # Composite and save
    # -----------------------------------------------------------------------

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