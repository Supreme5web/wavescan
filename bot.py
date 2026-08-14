import os
import time

import leaderboard
import pnl_card
import pnl_lookup
import storage
from config import BOT_NAME
from market import fetch_best_pair, get_ath_mc, get_market_cap
from telegram import (
    send_message, send_photo, send_photo_file, delete_message, answer_callback_query,
    edit_message_text, edit_message_caption,
)
from utils import (
    escape_md, escape_url, format_usd_short, format_price, format_pct,
    format_age, truncate_ca, parse_mc, find_ca, CA_RE,
)

ALERT_KEY = "alert:{chat_id}:{ca}:{user_id}"
GROUP_CHAT_TYPES = ("group", "supergroup")

START_MESSAGE = f"""
*{BOT_NAME}* — fast Solana \\& multi\\-chain token lookups and market\\-cap alerts, right in Telegram\\.

Commands:
/data `<ca>` \\- price, market cap, liquidity, volume
/alert `<ca> <target mc>` \\- ping me when a token hits a target mc \\(e\\.g\\. `500k`, `1\\.2m`\\)
/alerts \\- list your active alerts
/cancel `<ca>` \\- cancel an alert
/leaderboard \\- top callers in this group, ranked by best multiplier
/pnl `<ca>` \\- card showing this chat's first call on a token vs\\. its peak
/ping \\- check if the bot is alive
""".strip()

_SOCIAL_EMOJI = {"twitter": "🐦", "telegram": "✈️", "discord": "🎮"}


def _fmt_plain_compact(value) -> str:
    """5k / 400k / 1.2m style, no $ sign - used for the 'scanned by' line."""
    v = float(value or 0)
    if v >= 1_000_000_000:
        num, suffix = v / 1_000_000_000, "b"
    elif v >= 1_000_000:
        num, suffix = v / 1_000_000, "m"
    elif v >= 1_000:
        num, suffix = v / 1_000, "k"
    else:
        return f"{v:,.0f}"
    text = f"{num:.1f}".rstrip("0").rstrip(".")
    return f"{text}{suffix}"


def _action_keyboard(ca: str):
    return {"inline_keyboard": [[
        {"text": "🔄 Refresh", "callback_data": f"refresh:{ca}"},
        {"text": "🗑️ Delete", "callback_data": "delete"},
    ]]}


def _social_links_line(pair: dict) -> str:
    socials = (pair.get("info") or {}).get("socials") or []
    for social in socials:
        if social.get("type") in ("twitter", "x") and social.get("url"):
            return f"🔗 [𝕏]({escape_url(social['url'])})"
    return ""


def _fmt_change(value) -> str:
    v = float(value or 0)
    return f"{v:+.1f}" if v else "0.0"


def _fmt_th(pair: dict) -> str:
    events = pair.get("events") or {}
    keys = ("5m", "15m", "30m", "1h", "2h")
    values = []
    for key in keys:
        values.append(_fmt_change((events.get(key) or {}).get("priceChangePercentage")))
    change24 = float((events.get("24h") or {}).get("priceChangePercentage") or 0)
    return "| ".join(values), change24


def _build_token_message(pair: dict, ca: str, chat_id=None) -> str:
    base = pair.get("baseToken") or {}
    symbol = (base.get("symbol") or "UNKNOWN").upper()
    name = base.get("name") or symbol
    price = float(pair.get("priceUsd") or 0)
    mc = get_market_cap(pair)
    ath_mc = get_ath_mc(pair, mc)
    liq = float((pair.get("liquidity") or {}).get("usd") or 0)
    vol24 = float((pair.get("volume") or {}).get("h24") or 0)
    vol1h = float((pair.get("volume") or {}).get("h1") or 0)
    txns1h = (pair.get("txns") or {}).get("h1") or {}
    buys1h = int(txns1h.get("buys") or 0)
    sells1h = int(txns1h.get("sells") or 0)
    created_ms = pair.get("pairCreatedAt") or 0
    dex = str(pair.get("dexId") or "Unknown").replace("-", " ").title()
    holders = int(pair.get("holders") or 0)
    dev_pct = float(pair.get("devPercentage") or 0)
    dev_wallet = pair.get("devWallet") or ""
    dex_paid = bool(pair.get("dexPaid"))
    th, change24 = _fmt_th(pair)

    age = format_age(created_ms)
    if age == "0m":
        age = "<1m"

    dev_status = f"Holding 🚫 ({dev_pct:.1f}%)" if dev_pct > 0 else "Not Holding ✅ (0.0%)"
    wallet_short = f"{dev_wallet[:4]}...{dev_wallet[-4:]}" if len(dev_wallet) > 10 else (dev_wallet or "N/A")
    paid_line = "✅ Paid" if dex_paid else "❌ Not Paid"

    lines = [
        f"💸 *(${escape_md(symbol)})* {escape_md(name)} | ⌛{escape_md(age)} | {escape_md(dex)}",
        "",
        f"┏💰 MC: `{format_usd_short(mc)}` \(ATH `{format_usd_short(ath_mc)}`\)",
        f"├ 💵 Price: `{format_price(price)}`",
        f"├ 💧 Liquidity: `{format_usd_short(liq) if liq else 'N/A'}`",
        f"├📊 Vol: `{format_usd_short(vol24)}`",
        f"├1H: `{format_usd_short(vol1h)}`",
        f"┗ TH        `{th}` `[{change24:.0f}%]`",
        "",
        "👨‍💻 *Dev*",
        "┏ Status     " + escape_md(dev_status),
        "┣ Wallet      `" + escape_md(wallet_short) + "`",
        "┗ DEX Paid    " + escape_md(paid_line),
    ]

    socials_line = _social_links_line(pair)
    if socials_line:
        lines += ["", socials_line]

    lines += ["", f"`{escape_md(ca)}`"]

    # Compact terminal labels.
    lines += ["", "AXI • TRO • BONK • MAE • GMGN"]

    if chat_id is not None and pnl_lookup.available():
        first_call = pnl_lookup.get_first_call(chat_id, ca)
        if first_call:
            scanner = first_call.get("username") or first_call.get("first_name") or "someone"
            entry_mc = float(first_call.get("entry_mc") or 0)
            mult = mc / entry_mc if entry_mc else 0
            if mult >= 2:
                perf = f"{mult:.1f}x"
            else:
                perf = f"{(mult - 1) * 100:+.0f}%"
            lines += ["", f"1st scanned by {escape_md(scanner)} @ {escape_md(_fmt_plain_compact(entry_mc))} [{escape_md(perf)}]"]

    return "\n".join(lines)


def handle_data(chat_id, ca, message_id, user=None, chat_type=None):
    if not ca or not CA_RE.fullmatch(ca):
        send_message(chat_id, "Send a valid Solana contract address directly.", message_id)
        return
    pair = fetch_best_pair(ca)
    if not pair:
        send_message(chat_id, f"❌ No pair found for `{escape_md(truncate_ca(ca))}`", message_id)
        return

    if user and user.get("id") and leaderboard.available():
        mc = get_market_cap(pair)
        symbol = ((pair.get("baseToken") or {}).get("symbol") or "UNKNOWN").upper()
        if not leaderboard.record_call(chat_id, user, ca, symbol, pair.get("chainId"), mc):
            print(f"leaderboard record_call did not persist for chat={chat_id} ca={ca} mc={mc}")

    caption = _build_token_message(pair, ca, chat_id)
    keyboard = _action_keyboard(ca)
    image_url = (pair.get("info") or {}).get("imageUrl")

    if image_url and send_photo(chat_id, image_url, caption, message_id, keyboard):
        return
    send_message(chat_id, caption, message_id, keyboard)


def handle_alert(chat_id, text, message_id, user):
    parts = text.split()
    if len(parts) < 3:
        send_message(chat_id, "Usage: `/alert <contract address> <target mc>` e\\.g\\. `/alert <ca> 500k`", message_id)
        return

    ca, target_mc = parts[1], parse_mc(parts[2])
    if not CA_RE.fullmatch(ca):
        send_message(chat_id, "That doesn't look like a valid contract address\\.", message_id)
        return
    if not target_mc:
        send_message(chat_id, "Couldn't parse target market cap\\. Try `500k`, `1\\.2m`, etc\\.", message_id)
        return
    if not storage.available():
        send_message(chat_id, "⚠️ Alerts aren't configured on this deployment \\(missing Upstash env vars\\)\\.", message_id)
        return

    pair = fetch_best_pair(ca)
    if not pair:
        send_message(chat_id, f"❌ No pair found for `{escape_md(truncate_ca(ca))}`", message_id)
        return

    symbol = ((pair.get("baseToken") or {}).get("symbol") or "UNKNOWN").upper()
    key = ALERT_KEY.format(chat_id=chat_id, ca=ca, user_id=user["id"])
    record = {
        "ca": ca,
        "chatId": chat_id,
        "userId": user["id"],
        "username": user.get("username"),
        "firstName": user.get("first_name"),
        "symbol": symbol,
        "targetMc": target_mc,
        "createdAt": int(time.time() * 1000),
    }
    storage.set_json(key, record)
    send_message(chat_id, f"🔔 Alert set for *${escape_md(symbol)}* at {escape_md(format_usd_short(target_mc))} mc", message_id)


def handle_list_alerts(chat_id, user_id, message_id):
    if not storage.available():
        send_message(chat_id, "⚠️ Alerts aren't configured on this deployment\\.", message_id)
        return
    mine = [r for r in (storage.get_json(k) for k in storage.keys(f"alert:{chat_id}:*")) if r and r.get("userId") == user_id]
    if not mine:
        send_message(chat_id, "You have no active alerts\\.", message_id)
        return
    lines = ["*Your active alerts:*", ""]
    for r in mine:
        lines.append(f"• `{escape_md(truncate_ca(r['ca']))}` → {escape_md(format_usd_short(r['targetMc']))} mc")
    send_message(chat_id, "\n".join(lines), message_id)


def handle_cancel(chat_id, text, message_id, user):
    parts = text.split()
    if len(parts) < 2:
        send_message(chat_id, "Usage: `/cancel <contract address>`", message_id)
        return
    key = ALERT_KEY.format(chat_id=chat_id, ca=parts[1], user_id=user["id"])
    if storage.delete_key(key):
        send_message(chat_id, "🗑️ Alert cancelled\\.", message_id)
    else:
        send_message(chat_id, "No matching alert found\\.", message_id)


def _mention_row(row: dict) -> str:
    if row.get("username"):
        return f"@{escape_md(row['username'])}"
    return escape_md(row.get("first_name") or "trader")


def handle_leaderboard(chat_id, message_id, chat_type):
    if chat_type not in GROUP_CHAT_TYPES:
        send_message(chat_id, "🏆 The leaderboard only tracks calls made in group chats\\.", message_id)
        return
    if not leaderboard.available():
        send_message(chat_id, "⚠️ The leaderboard isn't configured on this deployment \\(missing Supabase env vars\\)\\.", message_id)
        return

    rows = leaderboard.top_callers(chat_id)
    if not rows:
        send_message(chat_id, "No calls tracked yet\\. Post a contract address in this chat to get on the board\\!", message_id)
        return

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 *TOP CALLERS*", "━" * 22]
    for i, row in enumerate(rows):
        rank = medals[i] if i < 3 else f"{i + 1}\\."
        entry_mc = row.get("entry_mc") or 0
        mult = (row.get("best_mc") or 0) / entry_mc if entry_mc else 0
        symbol = row.get("symbol") or "UNKNOWN"
        lines.append(
            f"{rank} {_mention_row(row)} — *${escape_md(symbol)}* "
            f"`{escape_md(f'{mult:.1f}x')}` \\({escape_md(truncate_ca(row['ca']))}\\)"
        )
    send_message(chat_id, "\n".join(lines), message_id)


def handle_pnl(chat_id, text, message_id):
    parts = text.split()
    ca = parts[1] if len(parts) >= 2 else find_ca(text)
    if not ca or not CA_RE.fullmatch(ca):
        send_message(chat_id, "Usage: `/pnl <contract address>`", message_id)
        return
    if not pnl_lookup.available():
        send_message(chat_id, "⚠️ PNL cards aren't configured on this deployment \\(missing Supabase env vars\\)\\.", message_id)
        return

    call = pnl_lookup.get_first_call(chat_id, ca)
    if not call:
        send_message(chat_id, "Nobody in this chat has called this token yet\\. Post the CA to log the first call\\!", message_id)
        return

    pair = fetch_best_pair(ca)
    base = (pair or {}).get("baseToken") or {}
    token_name = base.get("name") or call.get("symbol") or "Unknown"
    token_symbol = base.get("symbol") or call.get("symbol") or "?"
    logo_url = ((pair or {}).get("info") or {}).get("imageUrl")

    caller_handle = call.get("username") or call.get("first_name")

    path = None
    try:
        path = pnl_card.generate_pnl_card({
            "token_name": token_name,
            "token_symbol": token_symbol,
            "entry_mc": call["entry_mc"],
            "best_mc": call["best_mc"],
            "username": caller_handle,
            "logo_url": logo_url,
        })
        if not send_photo_file(chat_id, path, reply_to=message_id):
            send_message(chat_id, "⚠️ Couldn't generate the PNL card, try again\\.", message_id)
    finally:
        if path and os.path.exists(path):
            os.remove(path)


def handle_callback(callback_query: dict):
    """Handles the Refresh and Delete buttons under a /data card."""
    cq_id = callback_query["id"]
    data = callback_query.get("data") or ""
    message = callback_query.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")

    if data == "delete":
        # Restrict deletion to whoever triggered the original lookup — our
        # card is always sent as a reply to that command/CA message.
        requester_id = ((message.get("reply_to_message") or {}).get("from") or {}).get("id")
        caller_id = (callback_query.get("from") or {}).get("id")
        if requester_id and caller_id != requester_id:
            answer_callback_query(cq_id, "🚫 Only the person who requested this can delete it", show_alert=True)
            return
        if chat_id and message_id and delete_message(chat_id, message_id):
            answer_callback_query(cq_id, "🗑️ Deleted")
        else:
            answer_callback_query(cq_id, "⚠️ Couldn't delete \\(bot may lack permission here\\)", show_alert=True)
        return

    if not data.startswith("refresh:"):
        answer_callback_query(cq_id)
        return

    ca = data[len("refresh:"):]
    if not (ca and CA_RE.fullmatch(ca) and chat_id and message_id):
        answer_callback_query(cq_id, "⚠️ Can't refresh this message", show_alert=True)
        return

    pair = fetch_best_pair(ca)
    if not pair:
        answer_callback_query(cq_id, "❌ No pair found", show_alert=True)
        return

    caption = _build_token_message(pair, ca, chat_id)
    keyboard = _action_keyboard(ca)
    has_photo = bool(message.get("photo"))

    result = (
        edit_message_caption(chat_id, message_id, caption, keyboard)
        if has_photo else
        edit_message_text(chat_id, message_id, caption, keyboard)
    )

    if result is None:
        answer_callback_query(cq_id, "✅ Already up to date")
    elif result:
        answer_callback_query(cq_id, "🔄 Refreshed")
    else:
        answer_callback_query(cq_id, "⚠️ Refresh failed, try again", show_alert=True)


def handle_update(update: dict):
    if "callback_query" in update:
        handle_callback(update["callback_query"])
        return

    message = update.get("message")
    if not message:
        return

    chat_id = message["chat"]["id"]
    chat_type = (message.get("chat") or {}).get("type")
    text = (message.get("text") or "").strip()
    message_id = message["message_id"]
    user = message.get("from") or {}

    if text.startswith("/start"):
        send_message(chat_id, START_MESSAGE, message_id)
    elif text == "/ping":
        send_message(chat_id, "🏓 Pong\\! WaveScan is alive\\.", message_id)
    elif text.startswith("/alert") and not text.startswith("/alerts"):
        handle_alert(chat_id, text, message_id, user)
    elif text == "/alerts":
        handle_list_alerts(chat_id, user.get("id"), message_id)
    elif text.startswith("/cancel"):
        handle_cancel(chat_id, text, message_id, user)
    elif text.startswith("/leaderboard") or text.startswith("/lb"):
        handle_leaderboard(chat_id, message_id, chat_type)
    elif text.startswith("/pnl"):
        handle_pnl(chat_id, text, message_id)
    elif CA_RE.fullmatch(text):
        handle_data(chat_id, text, message_id, user, chat_type)
