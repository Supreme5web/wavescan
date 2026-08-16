import os
from urllib.parse import urlparse

from flask import Flask, Response, request, jsonify

import bot
import sweep
from config import BOT_NAME, CRON_SECRET

app = Flask(__name__)

_CARD_OG_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:image" content="{image_url}">
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


# Token logo link preview. bot.py sends a message with link_preview_options
# pointed at /card/<nonce>?img=<logo url> (a tiny page whose only job is an
# og:image meta tag) rather than uploading the logo via sendPhoto — Telegram
# scrapes this page and renders the token's own image inline. <nonce> is a
# fresh random token per send/refresh so Telegram never reuses a stale
# cached scrape of the same underlying logo URL.
_ALLOWED_IMG_SCHEMES = {"http", "https"}


@app.get("/card/<nonce>")
def token_card_page(nonce):
    image_url = request.args.get("img", "")
    parsed = urlparse(image_url)
    if parsed.scheme not in _ALLOWED_IMG_SCHEMES or not parsed.netloc:
        return "Invalid image URL", 400
    html = _CARD_OG_PAGE.format(title=BOT_NAME, image_url=image_url)
    return Response(html, mimetype="text/html", headers={"Cache-Control": "no-store"})


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
