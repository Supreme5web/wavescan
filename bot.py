import os
import secrets
import time
from datetime import datetime, timedelta, timezone

import leaderboard
import pnl_card
import pnl_lookup
import solana
import storage
from config import BOT_NAME, BOT_USERNAME, PUBLIC_BASE_URL, TRADING_BOTS
from market import fetch_best_pair, get_ath_mc, get_market_cap
from telegram import (
    send_message, send_photo_file, delete_message, answer_callback_query,
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


def _card_url(ca: str) -> str:
    """Fresh URL per render, pointing at the /card/<ca>/<nonce> page in
    app.py. The random nonce means Telegram's link-preview scraper always
    treats it as a URL it's never seen, so it never serves a stale cache
    from an earlier render of the same token."""
    nonce = secrets.token_hex(6)
    return f"{PUBLIC_BASE_URL}/card/{ca}/{nonce}"


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
        f"🍪 *_\\(${escape_md(symbol)}\\) {escape_md(name)} • ⌛{escape_md(age)} • {escape_md(dex)}_*",
        "",
        f"┏ *_💰 MC {escape_md(format_usd_short(mc))}  \\(ATH {escape_md(format_usd_short(ath_mc))}\\)_*",
        f"┣ *_💵 Price {escape_md(format_price(price))}_*",
        f"┣ *_💧 LP {escape_md(format_usd_short(liq))}_*",
        f"┣ *_📊 Vol {escape_md(format_usd_short(vol24))}_*",
        f"┣ *_⏱ 1H {escape_md(format_usd_short(vol1h))}_*",
        (
            f"┗ *_🎯 TH {th} \\({top10_total:.0f}%\\)_*"
            if th is not None
            else "┗ *_🎯 TH N/A_*"
        ),
        "",
        "👨‍💻 *_Dev_*",
        f"┏ *_Status {escape_md(dev_status)}_*",
        f"┣ *_Wallet {wallet_link}_*",
        f"┗ *_DEX Paid {escape_md(paid_line)}_*",
    ]

    socials_line = _social_links_line(pair)
    if socials_line:
        lines += ["", f"*_{socials_line}_*"]

    # Left as plain monospace (not bold/italic) so the address stays
    # tap-to-copy in Telegram.
    lines += ["", f"`{escape_md(ca)}`"]

    links_line = " • ".join(
        f"[{label}]({escape_url(build(ca))})" for label, build in TRADING_BOTS
    )
    lines += ["", f"*_{links_line}_*"]

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
                f"*_⚪[{escape_md(scanner)}]({escape_url(deep_link)}) @ "
                f"{escape_md(format_usd_short(entry_mc))} \\({escape_md(perf)}\\)"
            )
            if jump_link:
                footer += f" \\([{escape_md(age)}]({escape_url(jump_link)}) ago\\)_*"
            else:
                footer += f" \\({escape_md(age)} ago\\)_*"

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

    # Server-rendered overlay, embedded as a link preview (see app.py's
    # /card/<ca>/<nonce> route + token_card.py) rather than uploaded via
    # sendPhoto.
    send_message(chat_id, caption, message_id, keyboard, preview_url=_card_url(ca))


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
    username = row.get("username")
    if username:
        return f"[@{escape_md(username)}](https://t.me/{username})"
    label = escape_md(row.get("first_name") or "trader")
    user_id = row.get("user_id") or row.get("userId")
    if user_id:
        return f"[{label}](tg://user?id={user_id})"
    return label


LB_PERIODS = {"1h": 1, "4h": 4, "12h": 12, "1d": 24}
LB_DEFAULT_PERIOD = "1d"


def _leaderboard_keyboard(period: str):
    return {"inline_keyboard": [[
        {"text": f"• {p} •" if p == period else p, "callback_data": f"lb:{p}"}
        for p in LB_PERIODS
    ]]}


def _build_leaderboard_message(chat_id, period: str) -> str:
    hours = LB_PERIODS.get(period, LB_PERIODS[LB_DEFAULT_PERIOD])
    since_iso = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    calls = leaderboard.calls_since(chat_id, since_iso)
    if not calls:
        return f"📊 No calls tracked in the last {escape_md(period)}\\. Post a contract address in this chat to get on the board\\!"

    scored = []
    for row in calls:
        entry_mc = row.get("entry_mc") or 0
        best_mc = row.get("best_mc") or 0
        mult = (best_mc / entry_mc) if entry_mc else 0
        scored.append((mult, row))
    scored.sort(key=lambda x: x[0], reverse=True)

    total = len(scored)
    hits = sum(1 for m, _ in scored if m >= 2)
    hit_rate = (hits / total * 100) if total else 0
    avg_mult = (sum(m for m, _ in scored) / total) if total else 0
    top_mult, top_row = scored[0]

    top10 = scored[:10]
    lines = [
        "👑 *TOP CALLER*",
        f"└ 🥇 {_mention_row(top_row)}",
        "",
        "📊 *GROUP PERFORMANCE*",
        f"├ ⏱️ Period · {escape_md(period)}",
        f"├ 📞 Calls · {total}",
        f"├ 🎯 Hit Rate · {hit_rate:.0f}% ≥2x",
        f"└ 💰 Return · {escape_md(f'{top_mult:.1f}x')} · Avg {escape_md(f'{avg_mult:.1f}x')}",
        "",
        "🔥 *TOP CALLS*",
    ]
    for i, (mult, row) in enumerate(top10):
        prefix = "└" if i == len(top10) - 1 else "├"
        symbol = row.get("symbol") or "UNKNOWN"
        lines.append(
            f"{prefix} 🟣 {escape_md(symbol)} » {_mention_row(row)} •\\({escape_md(f'{mult:.1f}x')}\\)"
        )
    return "\n".join(lines)


def handle_leaderboard(chat_id, message_id, chat_type, period: str = LB_DEFAULT_PERIOD):
    if chat_type not in GROUP_CHAT_TYPES:
        send_message(chat_id, "🏆 The leaderboard only tracks calls made in group chats\\.", message_id)
        return
    if not leaderboard.available():
        send_message(chat_id, "⚠️ The leaderboard isn't configured on this deployment \\(missing Supabase env vars\\)\\.", message_id)
        return
    text = _build_leaderboard_message(chat_id, period)
    send_message(chat_id, text, message_id, _leaderboard_keyboard(period))


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

    if data.startswith("lb:"):
        period = data[len("lb:"):]
        if period not in LB_PERIODS:
            answer_callback_query(cq_id, "⚠️ Unknown period", show_alert=True)
            return
        if not leaderboard.available() or not chat_id or not message_id:
            answer_callback_query(cq_id, "⚠️ Leaderboard not configured", show_alert=True)
            return
        text = _build_leaderboard_message(chat_id, period)
        result = edit_message_text(chat_id, message_id, text, _leaderboard_keyboard(period))
        if result is None:
            answer_callback_query(cq_id, f"✅ Already on {period}")
        elif result:
            answer_callback_query(cq_id, f"📊 {period}")
        else:
            answer_callback_query(cq_id, "⚠️ Couldn't switch, try again", show_alert=True)
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

    # has_photo means this card predates the link-preview switch (it was
    # sent via sendPhoto) — its caption can still be edited in place, but
    # it can't retroactively become a link-preview message. New cards are
    # plain text with a link preview, refreshed to a fresh nonce each time
    # so Telegram rescrapes rather than reusing a stale image.
    result = (
        edit_message_caption(chat_id, message_id, caption, keyboard)
        if has_photo else
        edit_message_text(chat_id, message_id, caption, keyboard, preview_url=_card_url(ca))
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
