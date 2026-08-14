"""
pnl_card.py
-----------
PNL card renderer for the new 1672x941 WaveScan-style layout.

Put the supplied layout image in:
    assets/pnl_card_template.png

The template is the 1672x941 image supplied with the UI.  This renderer
removes the example token/logo/metrics from that template, preserves the
UI artwork (including the multiplier box), and then draws live values.

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
CYAN = (56, 189, 248, 255)

# ---------------------------------------------------------------------------
# Layout of the supplied 1672 x 941 image
# ---------------------------------------------------------------------------

# Header
LOGO_BOX = (68, 80, 308, 308)
NAME_X = 322
NAME_Y = 181
NAME_MAX_WIDTH = 820

# Multiplier box.  The box itself is already part of the artwork.
MULT_BOX = (440, 337, 1200, 596)

# Bottom metrics
CALLED_X = 294
REACHED_X = 654
CALLED_BY_X = 1077

LABEL_Y = 717
VALUE_Y = 762

# Divider positions in the supplied layout.
DIVIDER_1_X = 613
DIVIDER_2_X = 1024

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
    if mult >= 100:
        return f"{mult:,.0f}X"
    if mult >= 10:
        return f"{mult:.1f}X"
    return f"{mult:.2f}X"


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
        response = requests.get(logo_url, timeout=6)
        response.raise_for_status()
        logo = Image.open(io.BytesIO(response.content)).convert("RGBA")
    except Exception as exc:
        logger.warning("Could not fetch token logo from %s: %s", logo_url, exc)
        return None

    logo.thumbnail((size - 12, size - 12), Image.LANCZOS)

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


def _remove_example_content(img: Image.Image) -> Image.Image:
    """
    Remove the example content baked into the supplied screenshot while
    retaining the actual UI frame/artwork.

    The template's central multiplier panel and bottom background are mostly
    black, so these masks are deliberately conservative.
    """
    out = img.copy()
    draw = ImageDraw.Draw(out)

    # 1) Token logo interior.
    # Keep the cyan circular border, replace only its interior with a dark
    # transparent-looking fill. The live logo is drawn over this later.
    x0, y0, x1, y1 = LOGO_BOX
    draw.ellipse(
        (x0 + 7, y0 + 7, x1 - 7, y1 - 7),
        fill=(2, 5, 10, 255),
    )

    # 2) Example token name.
    # This is in a relatively dark header region, so paint only the text band.
    draw.rectangle(
        (NAME_X - 5, 170, 1130, 252),
        fill=(1, 4, 9, 255),
    )

    # Restore the subtle header glow/circuit area from a nearby dark band by
    # keeping the cleanup conservative; the live title is drawn afterward.

    # 3) Example multiplier text ONLY.
    # Preserve the neon box and border; clear the interior text area.
    mx0, my0, mx1, my1 = MULT_BOX
    draw.rectangle(
        (mx0 + 65, my0 + 35, mx1 - 65, my1 - 35),
        fill=(1, 5, 10, 255),
    )

    # 4) Bottom example metrics.
    # The supplied layout has a very dark lower band, so remove the example
    # labels/values without touching the outer border.
    draw.rectangle(
        (255, 704, 1505, 865),
        fill=(1, 4, 9, 255),
    )

    # Recreate the two cyan separators from the supplied layout.
    draw.line(
        (DIVIDER_1_X, 717, DIVIDER_1_X, 853),
        fill=(56, 189, 248, 180),
        width=2,
    )
    draw.line(
        (DIVIDER_2_X, 717, DIVIDER_2_X, 853),
        fill=(56, 189, 248, 180),
        width=2,
    )

    return out


def _draw_logo(draw, overlay, call):
    x0, y0, x1, y1 = LOGO_BOX
    size = x1 - x0

    logo = _fetch_logo(call.get("logo_url"), size)

    if logo:
        overlay.alpha_composite(logo, (x0, y0))
        draw.ellipse(
            LOGO_BOX,
            outline=CYAN,
            width=4,
        )
        return

    # Fallback placeholder.
    draw.ellipse(
        LOGO_BOX,
        fill=(8, 15, 27, 255),
        outline=CYAN,
        width=4,
    )

    symbol = str(call.get("token_symbol") or "?")[0].upper()
    font = _font(FONT_BOLD, 112)

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


def generate_pnl_card(call: dict) -> str:
    """
    Render the supplied UI layout with live call data and return a temporary
    PNG path. The caller is responsible for deleting the returned file.
    """

    if not os.path.isfile(TEMPLATE_PATH):
        raise FileNotFoundError(
            f"PNL template not found: {TEMPLATE_PATH}. "
            "Put the supplied UI image at assets/pnl_card_template.png"
        )

    base = Image.open(TEMPLATE_PATH).convert("RGBA")

    if base.size != (1672, 941):
        logger.warning(
            "pnl_card_template.png is %s; this layout was designed for 1672x941.",
            base.size,
        )

    # Remove the example data baked into the supplied image.
    cleaned = _remove_example_content(base)

    overlay = Image.new("RGBA", cleaned.size, (0, 0, 0, 0))
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
    # Token name / symbol
    # -----------------------------------------------------------------------
    name = str(call.get("token_name") or "Unknown Token")
    symbol = str(call.get("token_symbol") or "").upper()

    name_text = f"{name} (${symbol})" if symbol else name

    name_font = _fit_text(
        draw,
        name_text,
        FONT_BOLD,
        NAME_MAX_WIDTH,
        58,
        min_size=28,
    )

    draw.text(
        (NAME_X, NAME_Y),
        name_text,
        font=name_font,
        fill=WHITE,
    )

    # -----------------------------------------------------------------------
    # Multiplier
    # -----------------------------------------------------------------------
    mult_text = _fmt_mult(mult)

    mult_width = MULT_BOX[2] - MULT_BOX[0] - 90

    mult_font = _fit_text(
        draw,
        mult_text,
        FONT_BOLD,
        mult_width,
        150,
        min_size=70,
    )

    bbox = draw.textbbox(
        (0, 0),
        mult_text,
        font=mult_font,
    )

    mw = bbox[2] - bbox[0]
    mh = bbox[3] - bbox[1]

    center_x = (MULT_BOX[0] + MULT_BOX[2]) / 2
    center_y = (MULT_BOX[1] + MULT_BOX[3]) / 2

    mx = center_x - mw / 2 - bbox[0]
    my = center_y - mh / 2 - bbox[1]

    # Green/red glow.
    glow = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)

    glow_draw.text(
        (mx, my),
        mult_text,
        font=mult_font,
        fill=(*accent[:3], 120),
    )

    glow = glow.filter(ImageFilter.GaussianBlur(12))
    overlay.alpha_composite(glow)

    draw = ImageDraw.Draw(overlay)

    draw.text(
        (mx, my),
        mult_text,
        font=mult_font,
        fill=accent,
    )

    # -----------------------------------------------------------------------
    # Bottom metrics
    # -----------------------------------------------------------------------
    label_font = _font(FONT_BOLD, 28)
    value_font = _font(FONT_BOLD, 58)

    draw.text(
        (CALLED_X, LABEL_Y),
        "CALLED AT",
        font=label_font,
        fill=CYAN,
    )

    draw.text(
        (CALLED_X, VALUE_Y),
        _fmt_compact(entry_mc),
        font=value_font,
        fill=WHITE,
    )

    draw.text(
        (REACHED_X, LABEL_Y),
        "REACHED",
        font=label_font,
        fill=CYAN,
    )

    draw.text(
        (REACHED_X, VALUE_Y),
        _fmt_compact(best_mc),
        font=value_font,
        fill=accent,
    )

    # -----------------------------------------------------------------------
    # Called by
    # -----------------------------------------------------------------------
    username = call.get("username")

    if username:
        handle = str(username)
        if not handle.startswith("@"):
            handle = "@" + handle

        draw.text(
            (CALLED_BY_X, LABEL_Y),
            "CALLED BY",
            font=label_font,
            fill=CYAN,
        )

        handle_font = _fit_text(
            draw,
            handle,
            FONT_BOLD,
            430,
            58,
            min_size=30,
        )

        draw.text(
            (CALLED_BY_X, VALUE_Y),
            handle,
            font=handle_font,
            fill=WHITE,
        )

    # -----------------------------------------------------------------------
    # Composite and save.
    # -----------------------------------------------------------------------
    final_img = Image.alpha_composite(
        cleaned,
        overlay,
    ).convert("RGB")

    fd, output_path = tempfile.mkstemp(
        prefix="pnl_card_",
        suffix=".png",
        dir=tempfile.gettempdir(),
    )
    os.close(fd)

    final_img.save(output_path, "PNG", optimize=True)

    return output_path