"""Generate a crypto call PNL card using the new dark HUD UI.

Put the supplied `pnl_card_new_ui.png` in your project's `assets/` folder.
The background contains the frame, circuits, chart, hexagons and multiplier box.
This file draws the dynamic token logo/name, multiplier, metrics and caller.
"""

import io
import logging
import os
import tempfile
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(__file__)
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# New UI background. The first path is for a normal project layout.
TEMPLATE_PATH = os.path.join(ASSETS_DIR, "pnl_card_template")
if not os.path.exists(TEMPLATE_PATH):
    TEMPLATE_PATH = os.path.join(BASE_DIR, "pnl_card_template.png")

FONT_DIR = os.path.join(ASSETS_DIR, "fonts")
FONT_BOLD = os.path.join(FONT_DIR, "Rajdhani-Bold.ttf")
FONT_REGULAR = os.path.join(FONT_DIR, "Rajdhani-Medium.ttf")

WHITE = (255, 255, 255, 255)
LABEL_BLUE = (40, 157, 255, 255)
GREEN = (40, 224, 145, 255)
RED = (248, 113, 113, 255)
CYAN = (35, 190, 255, 255)

# ---------------------------------------------------------------------------
# Layout for the 1672 x 941 new UI
# ---------------------------------------------------------------------------

# Header
LOGO_LEFT = 55
LOGO_TOP = 48
LOGO_SIZE = 245
NAME_LEFT = 325
NAME_MAX_RIGHT = 1130

# Multiplier box already exists in the background.
MULT_LEFT = 1130
MULT_TOP = 285
MULT_RIGHT = 1580
MULT_BOTTOM = 445

# Bottom metrics
CALLED_X = 295
REACHED_X = 655
CALLER_X = 1080
METRIC_LABEL_Y = 720
METRIC_VALUE_Y = 765


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


def _fetch_logo(logo_url: Optional[str], size: int) -> Optional[Image.Image]:
    if not logo_url:
        return None

    try:
        response = requests.get(logo_url, timeout=6)
        response.raise_for_status()
        logo = Image.open(io.BytesIO(response.content)).convert("RGBA")
    except Exception as exc:
        logger.warning("Could not fetch token logo: %s", exc)
        return None

    logo = logo.resize((size, size), Image.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)

    circular = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    circular.paste(logo, (0, 0), mask)
    return circular


def _draw_logo(draw, overlay, logo_url, symbol):
    box = (
        LOGO_LEFT,
        LOGO_TOP,
        LOGO_LEFT + LOGO_SIZE,
        LOGO_TOP + LOGO_SIZE,
    )

    logo = _fetch_logo(logo_url, LOGO_SIZE)

    if logo:
        overlay.paste(logo, (LOGO_LEFT, LOGO_TOP), logo)
    else:
        draw.ellipse(box, fill=(8, 20, 45, 255))
        letter = (symbol or "?")[0].upper()
        font = _font(FONT_BOLD, 110)
        bbox = draw.textbbox((0, 0), letter, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text(
            (
                LOGO_LEFT + (LOGO_SIZE - w) / 2 - bbox[0],
                LOGO_TOP + (LOGO_SIZE - h) / 2 - bbox[1],
            ),
            letter,
            font=font,
            fill=WHITE,
        )

    # Neon ring
    glow = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse(box, outline=(*CYAN[:3], 190), width=12)
    glow = glow.filter(ImageFilter.GaussianBlur(12))
    overlay.alpha_composite(glow)
    ImageDraw.Draw(overlay).ellipse(box, outline=CYAN, width=5)


def _draw_glow_text(overlay, xy, text, font, fill, blur=8):
    glow = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).text(xy, text, font=font, fill=(*fill[:3], 100))
    glow = glow.filter(ImageFilter.GaussianBlur(blur))
    overlay.alpha_composite(glow)
    ImageDraw.Draw(overlay).text(xy, text, font=font, fill=fill)


def generate_pnl_card(call: dict) -> str:
    """Render and return a temporary PNG path.

    Required call keys:
        token_name, token_symbol, entry_mc, best_mc

    Optional:
        username, logo_url
    """

    base = Image.open(TEMPLATE_PATH).convert("RGBA")
    W, H = base.size
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    entry_mc = float(call["entry_mc"])
    best_mc = float(call["best_mc"])
    mult = best_mc / entry_mc if entry_mc else 0.0
    accent = GREEN if mult >= 1 else RED

    # ---------------------------------------------------------------
    # Token logo + full name in the top-left header
    # ---------------------------------------------------------------
    _draw_logo(
        draw,
        overlay,
        call.get("logo_url"),
        call.get("token_symbol", "?"),
    )
    draw = ImageDraw.Draw(overlay)

    name = f"{call['token_name']} (${call['token_symbol'].upper()})"
    name_font = _fit_text(
        draw,
        name,
        FONT_BOLD,
        NAME_MAX_RIGHT - NAME_LEFT,
        start_size=70,
        min_size=38,
    )

    bbox = draw.textbbox((0, 0), name, font=name_font)
    name_h = bbox[3] - bbox[1]
    name_y = LOGO_TOP + (LOGO_SIZE - name_h) / 2 - bbox[1]

    _draw_glow_text(
        overlay,
        (NAME_LEFT, name_y),
        name,
        name_font,
        WHITE,
        blur=7,
    )
    draw = ImageDraw.Draw(overlay)

    # Make the ticker portion blue by drawing the complete title in two parts.
    prefix = f"{call['token_name']} "
    ticker = f"(${call['token_symbol'].upper()})"
    prefix_w = draw.textlength(prefix, font=name_font)

    # Cover the previous full white title only where the ticker goes, then redraw.
    # This keeps long names fitting while giving the ticker the blue accent.
    ticker_x = NAME_LEFT + prefix_w
    ticker_w = draw.textlength(ticker, font=name_font)
    draw.rectangle(
        (ticker_x - 2, name_y - 4, ticker_x + ticker_w + 3, name_y + name_h + 4),
        fill=(0, 0, 0, 0),
    )
    # Transparent rectangles cannot erase the already composited glow, so redraw
    # the complete title cleanly, then accent the ticker.
    draw.text((NAME_LEFT, name_y), prefix, font=name_font, fill=WHITE)
    draw.text((ticker_x, name_y), ticker, font=name_font, fill=LABEL_BLUE)

    # ---------------------------------------------------------------
    # Large multiplier inside the existing HUD box
    # ---------------------------------------------------------------
    mult_text = _fmt_mult(mult)
    mult_font = _fit_text(
        draw,
        mult_text,
        FONT_BOLD,
        MULT_RIGHT - MULT_LEFT - 35,
        start_size=172,   # two points larger than the previous version
        min_size=90,
    )

    mb = draw.textbbox((0, 0), mult_text, font=mult_font)
    mw = mb[2] - mb[0]
    mh = mb[3] - mb[1]
    mx = MULT_LEFT + (MULT_RIGHT - MULT_LEFT - mw) / 2 - mb[0]
    my = MULT_TOP + (MULT_BOTTOM - MULT_TOP - mh) / 2 - mb[1]

    _draw_glow_text(
        overlay,
        (mx, my),
        mult_text,
        mult_font,
        accent,
        blur=12,
    )
    draw = ImageDraw.Draw(overlay)

    # ---------------------------------------------------------------
    # Bottom metrics
    # ---------------------------------------------------------------
    label_font = _font(FONT_REGULAR, 30)
    value_font = _font(FONT_BOLD, 62)

    draw.text((CALLED_X, METRIC_LABEL_Y), "CALLED AT", font=label_font, fill=LABEL_BLUE)
    draw.text((CALLED_X, METRIC_VALUE_Y), _fmt_compact(entry_mc), font=value_font, fill=WHITE)

    draw.text((REACHED_X, METRIC_LABEL_Y), "REACHED", font=label_font, fill=LABEL_BLUE)
    draw.text((REACHED_X, METRIC_VALUE_Y), _fmt_compact(best_mc), font=value_font, fill=accent)

    # Caller is at the bottom-right and uses the same visual scale as the metrics.
    username = call.get("username")
    if username:
        handle = str(username)
        if not handle.startswith("@"):
            handle = "@" + handle

        caller_label_font = _font(FONT_REGULAR, 30)
        caller_font = _font(FONT_BOLD, 62)

        draw.text(
            (CALLER_X, METRIC_LABEL_Y),
            "CALLED BY",
            font=caller_label_font,
            fill=LABEL_BLUE,
        )

        # Keep the handle inside the right border.
        max_handle_width = W - CALLER_X - 70
        caller_font = _fit_text(
            draw,
            handle,
            FONT_BOLD,
            max_handle_width,
            start_size=62,
            min_size=40,
        )

        handle_bbox = draw.textbbox((0, 0), handle, font=caller_font)
        handle_w = handle_bbox[2] - handle_bbox[0]
        handle_x = W - 70 - handle_w - handle_bbox[0]

        # Align the caller value to the right, like the new UI.
        draw.text(
            (handle_x, METRIC_VALUE_Y),
            handle,
            font=caller_font,
            fill=WHITE,
        )

    final_img = Image.alpha_composite(base, overlay).convert("RGB")

    fd, path = tempfile.mkstemp(
        prefix="pnl_card_",
        suffix=".png",
        dir=tempfile.gettempdir(),
    )
    os.close(fd)

    final_img.save(path, "PNG")
    return path