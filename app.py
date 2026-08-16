import os
import threading
import time

from flask import Flask, request, jsonify

import bot
import sweep
from config import BOT_NAME, CRON_SECRET

app = Flask(__name__)

# --- Background ATH refresher --------------------------------------------
# Runs sweep.fast_refresh_ath() (Dexscreener-based) every 10s so best_mc is
# already fresh in Supabase by the time /pnl reads it — fixes /pnl showing
# entry == best when nobody ran /data (which was the only other place that
# ratcheted best_mc on demand) since the token was first called.
#
# Caveat: if this is deployed with gunicorn -w N (N>1), each worker process
# starts its own copy of this loop. That's wasted duplicate Dexscreener
# calls, not a correctness bug (update_best only ratchets upward), but for
# a webhook bot like this you should run a single worker anyway
# (`gunicorn -w 1 app:app`) so Telegram updates aren't duplicated either.
_REFRESH_INTERVAL_SECONDS = 10
_refresher_started = False


def _background_refresh_loop():
    while True:
        try:
            sweep.fast_refresh_ath()
        except Exception as err:
            print("fast ATH refresh failed:", err)
        time.sleep(_REFRESH_INTERVAL_SECONDS)


def start_background_refresher():
    global _refresher_started
    if _refresher_started:
        return
    _refresher_started = True
    t = threading.Thread(target=_background_refresh_loop, daemon=True)
    t.start()
    print(f"Background ATH refresher started ({_REFRESH_INTERVAL_SECONDS}s interval, Dexscreener)")


start_background_refresher()


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
