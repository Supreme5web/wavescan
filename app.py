import os

from flask import Flask, Response, request, jsonify

import bot
import sweep
import token_card
from config import BOT_NAME, CRON_SECRET, PUBLIC_BASE_URL
from market import fetch_best_pair
from utils import CA_RE

app = Flask(__name__)

_CARD_OG_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:image" content="{image_url}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{image_url}">
<title>{title}</title>
</head>
<body></body>
</html>"""


@app.get("/")
def health():
    return f"{BOT_NAME} bot is running ✅", 200


@app.post("/webhook")
def webhook():
    update = request.get_json(force=True, silent=True) or {}
    try:
        bot.handle_update(update)
    except Exception as err:
        print("handle_update failed:", err)
    return jsonify(ok=True)


# Token overlay link preview. bot.py sends a message with link_preview_options
# pointed at /card/<ca>/<nonce> (a tiny page whose only job is an og:image
# meta tag) rather than uploading the card via sendPhoto — Telegram scrapes
# this page and renders the image inline. <nonce> is a fresh random token
# per send/refresh so Telegram never reuses a stale cached scrape.
@app.get("/card/<ca>/<nonce>")
def token_card_page(ca, nonce):
    if not CA_RE.fullmatch(ca):
        return "Invalid contract address", 400
    image_url = f"{PUBLIC_BASE_URL}/card/{ca}/{nonce}.png"
    html = _CARD_OG_PAGE.format(title=f"{BOT_NAME} \u00b7 {ca}", image_url=image_url)
    return Response(html, mimetype="text/html", headers={"Cache-Control": "no-store"})


@app.get("/card/<ca>/<nonce>.png")
def token_card_image(ca, nonce):
    if not CA_RE.fullmatch(ca):
        return "Invalid contract address", 400
    pair = fetch_best_pair(ca)
    if not pair:
        return "Not found", 404
    try:
        png_bytes = token_card.generate_token_card_bytes(pair, ca)
    except Exception as err:
        print("token card render failed:", err)
        return "Render failed", 500
    return Response(png_bytes, mimetype="image/png", headers={"Cache-Control": "no-store"})


# Alert sweep, reachable over HTTP so a free external scheduler (e.g.
# cron-job.org) can trigger it — an alternative to Render's paid Cron Job
# service when running WaveScan as a single free Web Service.
# Set CRON_SECRET and call this as /sweep?secret=YOUR_SECRET on a schedule.
@app.get("/sweep")
@app.post("/sweep")
def sweep_endpoint():
    if CRON_SECRET:
        auth_header = request.headers.get("Authorization", "")
        supplied = request.args.get("secret") or auth_header.replace("Bearer ", "", 1)
        if supplied != CRON_SECRET:
            return jsonify(ok=False, error="Unauthorized"), 401
    try:
        result = sweep.run()
    except Exception as err:
        print("sweep failed:", err)
        return jsonify(ok=False, error=str(err)), 500
    return jsonify(ok=True, **(result or {}))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
