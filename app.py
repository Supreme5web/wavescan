import os

from flask import Flask, request, jsonify

import bot
import sweep
from config import BOT_NAME, CRON_SECRET

app = Flask(__name__)


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
