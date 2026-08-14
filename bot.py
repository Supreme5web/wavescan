import os
import time

import leaderboard
import pnl_card
import pnl_lookup
import solana
import storage
from config import BOT_NAME, BOT_USERNAME, TRADING_BOTS
from market import fetch_best_pair, get_ath_mc, get_market_cap
from telegram import (
    send_message, send_photo, send_photo_file, delete_message, answer_callback_query,
    edit_message_text, edit_message_caption,
)
from utils import (
    escape_md, escape_url, format_usd_short, format_price, format_pct,
    format_age, truncate_ca, parse_mc, find_ca, parse_iso_ms, CA_RE,
)

ALERT_KEY = "alert:{chat_id}:{ca}:{user_id}"
GROUP_CHAT_TYPES = ("group", "supergroup")

START_MESSAGE = f"""
*{BOT_NAME}* — fast Solana \\& multi\\-chain token lookups and market\\-cap alerts, right in Telegram\\.

Commands:
/alert `<ca> <target mc>` \\- ping me when a token hits a target mc \\(e\\.g\\. `500k`, `1\\.2m`\\)
/alerts \\- list your active alerts
/cancel `<ca>` \\- cancel an alert
/leaderboard \\- top callers in this group, ranked by best multiplier
/pnl `<ca>` \\- card showing this chat's first call on a token vs\\. its peak
/ping \\- check if the bot is alive
""".strip()

_SOCIAL_EMOJI = {"twitter": "🐦", "telegram": "✈️", "discord": "🎮"}


def _jump_link(chat_id, message_id):
    """Deep link straight to a message in a supergroup, or None if this
    chat isn't a supergroup (no -100 prefix) or there's no message_id."""
    if not message_id:
        return None
    chat_str = str(chat_id)
    if chat_str.startswith("-100"):
        return f"https://t.me/c/{chat_str[4:]}/{message_id}"
    return None


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


def _fmt_top_holders(ca: str, chain_id: str):
    """Top 5 individual holder percentages (each linked to its wallet on
    Solscan), plus the top-10 total for the bracket. Solana-only
    (RPC-based); returns (None, None) otherwise/on failure so the caller
    can show N/A instead of a wrong number."""
    if chain_id != "solana":
        return None, None
    holders = solana.get_top_holders(ca)
    if not holders:
        return None, None
    top5 = holders[:5]
    values = " \\| ".join(
        f"[{escape_md(f'{p:.1f}')}]({escape_url(f'https://solscan.io/account/{addr}')})"
        if addr else escape_md(f"{p:.1f}")
        for addr, p in top5
    )
    top10_total = sum(p for _, p in holders)
    return values, top10_total


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
    th, top10_total = _fmt_top_holders(ca, pair.get("chainId"))

    age = format_age(created_ms)
    if age == "0m":
        age = "<1m"

    dev_status = "Hold 🚫" if dev_pct > 0 else "Sold✅"
    wallet_short = f"{dev_wallet[:4]}...{dev_wallet[-4:]}" if len(dev_wallet) > 10 else (dev_wallet or "N/A")
    paid_line = "✅ Paid" if dex_paid else "❌ Not Paid"
    wallet_link = (
        f"[{escape_md(wallet_short)}]({escape_url(f'https://solscan.io/account/{dev_wallet}')})"
        if dev_wallet else escape_md(wallet_short)
    )

    lines = [
        f"💸 *\\(${escape_md(symbol)}\\)* {escape_md(name)} \\| ⌛{escape_md(age)} \\| {escape_md(dex)}",
        "",
        f"┏ MC:      *{escape_md(format_usd_short(mc))}* \\(ATH *{escape_md(format_usd_short(ath_mc))}*\\)",
        f"┣ Price:   *{escape_md(format_price(price))}*",
        f"┣ LP:      *{escape_md(format_usd_short(liq))}*",
        f"┣ Vol:     *{escape_md(format_usd_short(vol24))}*",
        f"┣1H:      *{escape_md(format_usd_short(vol1h))}*",
        (
            f"┗ TH:      {th} *\\[{top10_total:.0f}%\\]*"
            if th is not None
            else "┗ TH:      *N/A*"
        ),
        "",
        "👨‍💻 *Dev*",
        "┏ Status     *" + escape_md(dev_status) + "*",
        "┣ Wallet      " + wallet_link,
        "┗ DEX Paid    *" + escape_md(paid_line) + "*",
    ]

    socials_line = _social_links_line(pair)
    if socials_line:
        lines += ["", socials_line]

    lines += ["", f"`{escape_md(ca)}`"]

    links_line = " • ".join(
        f"[{label}]({escape_url(build(ca))})" for label, build in TRADING_BOTS
    )
    lines += ["", links_line]

    if chat_id is not None and pnl_lookup.available():
        first_call = pnl_lookup.get_first_call(chat_id, ca)
        if first_call:
            scanner = first_call.get("username") or first_call.get("first_name") or "someone"
            entry_mc = float(first_call.get("entry_mc") or 0)
            mult = mc / entry_mc if entry_mc else 0
            perf = f"{mult:.1f}x" if mult >= 2 else f"{(mult - 1) * 100:.0f}%"

            deep_link = f"https://t.me/{BOT_USERNAME}?start=call_{chat_id}_{first_call.get('user_id', '')}"
            age = format_age(parse_iso_ms(first_call.get("called_at")))
            jump_link = _jump_link(chat_id, first_call.get("message_id"))

            footer = (
                f"💢[{escape_md(scanner)}]({escape_url(deep_link)}) @ "
                f"{escape_md(format_usd_short(entry_mc))} \\[{escape_md(perf)}\\]"
            )
            if jump_link:
                footer += f" \\([{escape_md(age)}]({escape_url(jump_link)}) ago\\)"
            else:
                footer += f" \\({escape_md(age)} ago\\)"

            lines += ["", footer]

    return "\n".join(lines)


def handle_data(chat_id, ca, message_id, user=None, chat_type=None):
    if not ca or not CA_RE.fullmatch(ca):
        send_message(chat_id, "Send a valid Solana contract address directly.", message_id)
        return
    pair = fetch_best_pair(ca)
    if not pair:
        send_message(chat_id, f"❌ No pair found for `{escape_md(truncate_ca(ca))}`", message_id)
        return

    if leaderboard.available():
        mc = get_market_cap(pair)
        if user and user.get("id"):
            symbol = ((pair.get("baseToken") or {}).get("symbol") or "UNKNOWN").upper()
            if not leaderboard.record_call(chat_id, user, ca, symbol, pair.get("chainId"), mc, message_id):
                print(f"leaderboard record_call did not persist for chat={chat_id} ca={ca} mc={mc}")
        # Ratchet best_mc using this live lookup too, not just the periodic
        # sweep, so /pnl and /leaderboard reflect the current price sooner.
        leaderboard.update_best(chat_id, ca, mc)

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
            f"`{escape_md(f'{mult:.1f}x')}`"
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

    # Use this fresh lookup to ratchet best_mc too, so the card reflects the
    # live price instead of a stale value if the periodic sweep hasn't run.
    best_mc = float(call["best_mc"])
    if pair:
        live_mc = get_market_cap(pair)
        if live_mc > best_mc:
            best_mc = live_mc
            leaderboard.update_best(chat_id, ca, live_mc)

    path = None
    try:
        path = pnl_card.generate_pnl_card({
            "token_name": token_name,
            "token_symbol": token_symbol,
            "entry_mc": call["entry_mc"],
            "best_mc": best_mc,
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
