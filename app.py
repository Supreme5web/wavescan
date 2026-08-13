import os

from flask import Flask, request, jsonify

import bot
from config import BOT_NAME

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
