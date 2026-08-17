"""
pnl_card.py
-----------
PNL card renderer for the "SYSTEM OVERRIDE" WaveScan layout (1672x941).

Put the new blank template image at:
    assets/pnl_card_template.png

Unlike the previous version, this template ships CLEAN — no example
token/logo/metrics baked into it — so this renderer no longer paints
any masking rectangles over the artwork before drawing. That's what was
causing the "weird background" patches: the old template had example
content burned in, so parts of it had to be painted over with solid
dark rectangles before the real values were drawn on top. Those
clean-up rectangles didn't line up with this template's box borders and
ate into the character artwork on the right. With a blank template we
just draw straight onto it.

Expected call dict:
    token_name
    token_symbol
    entry_mc
    best_mc
    username   (optional)
    logo_url   (optional)
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

TEMPLATE_PATH = os.path.join(ASSETS_DIR, "pnl_card_template.png")

FONT_DIR = os.path.join(ASSETS_DIR, "fonts")
FONT_BOLD = os.path.join(FONT_DIR, "Rajdhani-Bold.ttf")
FONT_REGULAR = os.path.join(FONT_DIR, "Rajdhani-Medium.ttf")

WHITE = (255, 255, 255, 255)
GRAY = (148, 168, 200, 255)
GREEN = (52, 211, 153, 255)
RED = (248, 113, 113, 255)
# Accent used for labels / bullet marks / the small icons row — this
# template's theme color is red, not the old cyan.
ACCENT = (239, 68, 68, 255)

# ---------------------------------------------------------------------------
# Layout of the new 1672 x 941 "SYSTEM OVERRIDE" template.
# Measured directly off the supplied template/example images. The two
# content boxes on the template live at roughly:
#   top box:    x 88-805,  y 320-613   (multiplier panel)
#   bottom box: x 88-1005, y 686-858   (called-at / reached / called-by)
# Everything below is kept safely inside those bounds so nothing spills
# onto the border art or the character artwork on the right.
# ---------------------------------------------------------------------------

# Header (logo + name sit above the top box, same as the reference image)
LOGO_BOX = (80, 78, 280, 278)  # 200px circle

NAME_X = 322
NAME_Y = 118
NAME_MAX_WIDTH = 460

SYMBOL_X = 322
SYMBOL_Y = 205
SYMBOL_MAX_WIDTH = 460

# "CURRENT MULTIPLIER" label + big value, inside the top box
MULT_LABEL_BAR = (100, 351, 106, 369)  # small accent bar before the label
MULT_LABEL_X = 116
MULT_LABEL_Y = 351

MULT_VALUE_X = 100
MULT_VALUE_Y = 390
MULT_MAX_WIDTH = 675  # keeps the value inside the top box (right edge ~805)

# Bottom metrics row, inside the bottom box
CALLED_X = 120
REACHED_X = 465
CALLED_BY_X = 785
CALLED_BY_MAX_WIDTH = 200  # keeps the handle inside the bottom box (~1005)

LABEL_Y = 700
VALUE_Y = 743

# ---------------------------------------------------------------------------


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
    """Always one decimal place (e.g. 1.5X), except triple digits and up
    where a decimal doesn't add anything useful (e.g. 143X)."""
    if mult >= 100:
        return f"{mult:,.0f}X"
    return f"{mult:.1f}X"


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
        # Kept short — this sits directly in the send path, and a slow
        # logo host shouldn't be able to stall the whole card.
        response = requests.get(logo_url, timeout=4)
        response.raise_for_status()
        logo = Image.open(io.BytesIO(response.content)).convert("RGBA")
    except Exception as exc:
        logger.warning("Could not fetch token logo from %s: %s", logo_url, exc)
        return None

    logo.thumbnail((size - 10, size - 10), Image.LANCZOS)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - logo.width) // 2
    y = (size - logo.height) // 2
    canvas.alpha_composite(logo, (x, y))

    # Circular clipping.
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)

    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(canvas, (0, 0), mask)
    return result


def _draw_logo(draw, overlay, call):
    x0, y0, x1, y1 = LOGO_BOX
    size = x1 - x0

    logo = _fetch_logo(call.get("logo_url"), size)

    if logo:
        overlay.alpha_composite(logo, (x0, y0))
        draw.ellipse(LOGO_BOX, outline=ACCENT, width=3)
        return

    # Fallback placeholder.
    draw.ellipse(LOGO_BOX, fill=(8, 15, 27, 255), outline=ACCENT, width=3)

    symbol = str(call.get("token_symbol") or "?")[0].upper()
    font = _font(FONT_BOLD, 92)

    bbox = draw.textbbox((0, 0), symbol, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]

    draw.text(
        (
            (x0 + x1 - w) / 2 - bbox[0],
            (y0 + y1 - h) / 2 - bbox[1],
        ),
        symbol,
        font=font,
        fill=WHITE,
    )


def _draw_glow_text(overlay, xy, text, font, color, blur_radius=12, pad=40):
    """Draw `text` with a soft color glow behind it, without blurring the
    whole canvas. Older code ran GaussianBlur over the full 1672x941
    overlay just to glow a few hundred pixels of text — this crops a
    small patch around the text, blurs only that, then pastes it back.
    That's the single biggest chunk of render time this function had."""
    x, y = xy
    draw = ImageDraw.Draw(overlay)
    bbox = draw.textbbox((x, y), text, font=font)

    patch_box = (
        max(0, int(bbox[0] - pad)),
        max(0, int(bbox[1] - pad)),
        min(overlay.width, int(bbox[2] + pad)),
        min(overlay.height, int(bbox[3] + pad)),
    )

    glow_patch = Image.new("RGBA", (patch_box[2] - patch_box[0], patch_box[3] - patch_box[1]), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_patch)
    glow_draw.text((x - patch_box[0], y - patch_box[1]), text, font=font, fill=(*color[:3], 120))
    glow_patch = glow_patch.filter(ImageFilter.GaussianBlur(blur_radius))

    overlay.alpha_composite(glow_patch, (patch_box[0], patch_box[1]))

    draw = ImageDraw.Draw(overlay)
    draw.text((x, y), text, font=font, fill=color)


def generate_pnl_card(call: dict) -> str:
    """
    Render the SYSTEM OVERRIDE template with live call data and return a
    temporary PNG path. The caller is responsible for deleting the
    returned file.
    """

    if not os.path.isfile(TEMPLATE_PATH):
        raise FileNotFoundError(
            f"PNL template not found: {TEMPLATE_PATH}. "
            "Put the new template image at assets/pnl_card_template.png"
        )

    base = Image.open(TEMPLATE_PATH).convert("RGBA")

    if base.size != (1672, 941):
        logger.warning(
            "pnl_card_template.png is %s; this layout was designed for 1672x941.",
            base.size,
        )

    # Template ships blank, so we draw straight onto a copy of it — no
    # masking rectangles needed.
    overlay = base.copy()
    draw = ImageDraw.Draw(overlay)

    entry_mc = float(call["entry_mc"])
    best_mc = float(call["best_mc"])
    mult = best_mc / entry_mc if entry_mc else 0.0

    accent = GREEN if mult >= 1 else RED

    # -----------------------------------------------------------------------
    # Token logo
    # -----------------------------------------------------------------------
    _draw_logo(draw, overlay, call)
    draw = ImageDraw.Draw(overlay)

    # -----------------------------------------------------------------------
    # Token name / symbol (two lines, matching the new template)
    # -----------------------------------------------------------------------
    name = str(call.get("token_name") or "Unknown Token")
    symbol = str(call.get("token_symbol") or "")

    name_font = _fit_text(draw, name, FONT_BOLD, NAME_MAX_WIDTH, 62, min_size=28)
    draw.text((NAME_X, NAME_Y), name, font=name_font, fill=WHITE)

    if symbol:
        symbol_text = f"${symbol.upper()}"
        symbol_font = _fit_text(draw, symbol_text, FONT_REGULAR, SYMBOL_MAX_WIDTH, 38, min_size=20)
        draw.text((SYMBOL_X, SYMBOL_Y), symbol_text, font=symbol_font, fill=GRAY)

    # -----------------------------------------------------------------------
    # "CURRENT MULTIPLIER" label + value
    # -----------------------------------------------------------------------
    draw.rectangle(MULT_LABEL_BAR, fill=ACCENT)
    label_font = _font(FONT_BOLD, 26)
    draw.text((MULT_LABEL_X, MULT_LABEL_Y), "CURRENT MULTIPLIER", font=label_font, fill=ACCENT)

    mult_text = _fmt_mult(mult)
    mult_font = _fit_text(draw, mult_text, FONT_BOLD, MULT_MAX_WIDTH, 150, min_size=70)

    _draw_glow_text(overlay, (MULT_VALUE_X, MULT_VALUE_Y), mult_text, mult_font, accent)
    draw = ImageDraw.Draw(overlay)

    # -----------------------------------------------------------------------
    # Bottom metrics
    # -----------------------------------------------------------------------
    label_font = _font(FONT_BOLD, 24)
    value_font = _font(FONT_BOLD, 54)

    draw.text((CALLED_X, LABEL_Y), "CALLED AT", font=label_font, fill=ACCENT)
    draw.text((CALLED_X, VALUE_Y), _fmt_compact(entry_mc), font=value_font, fill=WHITE)

    draw.text((REACHED_X, LABEL_Y), "REACHED", font=label_font, fill=ACCENT)
    draw.text((REACHED_X, VALUE_Y), _fmt_compact(best_mc), font=value_font, fill=accent)

    username = call.get("username")
    if username:
        handle = str(username)
        if not handle.startswith("@"):
            handle = "@" + handle

        draw.text((CALLED_BY_X, LABEL_Y), "CALLED BY", font=label_font, fill=ACCENT)

        handle_font = _fit_text(draw, handle, FONT_BOLD, CALLED_BY_MAX_WIDTH, 54, min_size=26)
        draw.text((CALLED_BY_X, VALUE_Y), handle, font=handle_font, fill=WHITE)

    # -----------------------------------------------------------------------
    # Composite and save.
    # -----------------------------------------------------------------------
    final_img = overlay.convert("RGB")

    fd, output_path = tempfile.mkstemp(prefix="pnl_card_", suffix=".png", dir=tempfile.gettempdir())
    os.close(fd)

    # `optimize=True` on a full 1672x941 PNG is the other big chunk of the
    # old 10s: PIL's PNG optimizer re-tries multiple filter/compression
    # strategies to squeeze out extra bytes, which is slow and buys almost
    # nothing here since Telegram re-compresses the photo anyway. Dropping
    # it (and using a fast compress level) cuts save time substantially
    # with no visible quality difference.
    final_img.save(output_path, "PNG", optimize=False, compress_level=1)

    return output_path
