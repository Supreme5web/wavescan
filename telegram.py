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


def send_photo(chat_id, photo_url, caption, reply_to=None, keyboard=None) -> bool:
    """Send a remote image (e.g. a token logo) with a MarkdownV2 caption.
    Returns False on failure so the caller can fall back to a text message."""
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": "MarkdownV2",
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
        payload["allow_sending_without_reply"] = True
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        r = requests.post(f"{TELEGRAM_API}/sendPhoto", json=payload, timeout=12)
        if r.ok:
            return True
        print("sendPhoto rejected:", r.text)
        return False
    except Exception as err:
        print("sendPhoto failed:", err)
        return False
