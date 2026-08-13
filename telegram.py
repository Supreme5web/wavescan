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


def delete_message(chat_id, message_id) -> bool:
    """Delete a message (used by the Delete button). Bots can always delete
    their own messages; in groups this doesn't require admin rights."""
    try:
        r = requests.post(
            f"{TELEGRAM_API}/deleteMessage",
            json={"chat_id": chat_id, "message_id": message_id},
            timeout=10,
        )
        if r.ok:
            return True
        print("deleteMessage rejected:", r.text)
        return False
    except Exception as err:
        print("deleteMessage failed:", err)
        return False


def answer_callback_query(callback_query_id, text=None, show_alert=False):
    """Ack a button tap so Telegram stops showing the loading spinner on it."""
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = True
    try:
        r = requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json=payload, timeout=10)
        if not r.ok:
            print("answerCallbackQuery rejected:", r.text)
    except Exception as err:
        print("answerCallbackQuery failed:", err)


def edit_message_text(chat_id, message_id, text, keyboard=None):
    """Edit a plain-text message in place (used by the Refresh button).
    Returns True on success, None if Telegram says nothing changed, False on failure."""
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        r = requests.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=10)
        if r.ok:
            return True
        if "message is not modified" in r.text:
            return None
        print("editMessageText rejected:", r.text)
        return False
    except Exception as err:
        print("editMessageText failed:", err)
        return False


def edit_message_caption(chat_id, message_id, caption, keyboard=None):
    """Edit a photo message's caption in place (used by the Refresh button).
    Returns True on success, None if Telegram says nothing changed, False on failure."""
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "caption": caption,
        "parse_mode": "MarkdownV2",
    }
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        r = requests.post(f"{TELEGRAM_API}/editMessageCaption", json=payload, timeout=10)
        if r.ok:
            return True
        if "message is not modified" in r.text:
            return None
        print("editMessageCaption rejected:", r.text)
        return False
    except Exception as err:
        print("editMessageCaption failed:", err)
        return False
