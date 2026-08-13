import requests

from config import TELEGRAM_API
from utils import escape_md  # re-exported for convenience


def send_message(chat_id, text, reply_to=None, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
        payload["allow_sending_without_reply"] = True
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        r = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)
        if not r.ok:
            print("sendMessage rejected:", r.text)
    except Exception as err:
        print("sendMessage failed:", err)
