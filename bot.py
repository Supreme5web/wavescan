import time

import solana
import storage
from config import BOT_NAME, TRADING_BOTS
from market import fetch_best_pair, fetch_peak_price
from telegram import send_message, send_photo
from utils import (
    escape_md, escape_url, format_usd_short, format_price, format_pct,
    format_age, risk_label, truncate_ca, parse_mc, find_ca, CA_RE,
)

ALERT_KEY = "alert:{chat_id}:{ca}:{user_id}"

START_MESSAGE = f"""
*{BOT_NAME}* — fast Solana \\& multi\\-chain token lookups and market\\-cap alerts, right in Telegram\\.

Commands:
/data `<ca>` \\- price, market cap, liquidity, volume
/alert `<ca> <target mc>` \\- ping me when a token hits a target mc \\(e\\.g\\. `500k`, `1\\.2m`\\)
/alerts \\- list your active alerts
/cancel `<ca>` \\- cancel an alert
/ping \\- check if the bot is alive
""".strip()


def _trade_keyboard(ca: str):
    buttons = [{"text": label, "url": build(ca)} for label, build in TRADING_BOTS]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    rows.append([{"text": "📋 Copy CA", "copy_text": {"text": ca}}])
    return {"inline_keyboard": rows}


def _social_links_line(pair: dict) -> str:
    info = pair.get("info") or {}
    label_map = {"twitter": "Twitter", "telegram": "Telegram", "discord": "Discord"}
    socials = sorted(info.get("socials") or [], key=lambda s: 0 if s.get("type") == "telegram" else 1)

    parts = []
    for s in socials:
        url = s.get("url")
        if url:
            label = label_map.get(s.get("type"), (s.get("type") or "Link").title())
            parts.append(f"[{label}]({escape_url(url)})")
    websites = info.get("websites") or []
    if websites and websites[0].get("url"):
        parts.append(f"[Website]({escape_url(websites[0]['url'])})")
    return " • ".join(parts)


def _build_token_message(pair: dict, ca: str) -> str:
    base = pair.get("baseToken") or {}
    symbol = (base.get("symbol") or "UNKNOWN").upper()
    name = base.get("name") or symbol
    price = float(pair.get("priceUsd") or 0)
    mc = pair.get("fdv") or pair.get("marketCap") or 0
    liq = (pair.get("liquidity") or {}).get("usd") or 0
    vol24 = (pair.get("volume") or {}).get("h24") or 0
    vol1h = (pair.get("volume") or {}).get("h1") or 0
    change24 = (pair.get("priceChange") or {}).get("h24") or 0
    chain_id = pair.get("chainId") or "unknown"
    pool = pair.get("pairAddress")
    created_ms = pair.get("pairCreatedAt")
    txns1h = (pair.get("txns") or {}).get("h1") or {}
    buys1h, sells1h = txns1h.get("buys", 0), txns1h.get("sells", 0)
    total1h = buys1h + sells1h

    # ATH market cap from DexPaprika's OHLCV history since the pool was
    # created — a live snapshot alone would miss a spike that's already receded.
    ath_mc = mc
    if price > 0 and mc > 0 and pool and created_ms:
        peak_price = fetch_peak_price(chain_id, pool, created_ms)
        if peak_price > 0:
            ath_mc = max(ath_mc, peak_price * (mc / price))

    # Holder concentration is only computable for Solana here, via free
    # public RPC (no paid indexer) — omitted entirely for other chains or on
    # RPC failure/timeout rather than showing a guessed number.
    holders = top10_pct = None
    if chain_id == "solana":
        holders = solana.get_holder_count(ca)
        top10_pct = solana.get_top10_concentration(ca)

    lines = [
        f"💎 {escape_md(name)} \\(${escape_md(symbol)}\\) • {escape_md(chain_id.title())} 💊",
        "━" * 22,
        "📊 *MARKET METRICS*",
        f"• Market Cap: {escape_md(format_usd_short(mc))}  \\(ATH: {escape_md(format_usd_short(ath_mc))}\\)",
        f"• Price: `{format_price(price)}`  \\[{escape_md(format_pct(change24))}\\]",
        f"• Liquidity: {escape_md(format_usd_short(liq))}",
        f"• Volume 24h: {escape_md(format_usd_short(vol24))}  \\|  1H: {escape_md(format_usd_short(vol1h))}",
        "",
        "⚡ FLOW & MOMENTUM",
    ]

    if total1h:
        buy_pct = buys1h / total1h * 100
        lines.append(f"• 1H Trades: {buys1h} 🟢 / {sells1h} 🔴  \\({buy_pct:.0f}% Buys\\)")
    else:
        lines.append("• 1H Trades: N/A")
    if holders is not None:
        lines.append(f"• Holders: {holders}")
    lines.append(f"• Age: {escape_md(format_age(created_ms))}")

    if top10_pct is not None:
        emoji, label = risk_label(top10_pct)
        lines += ["", f"• Top 10: {emoji} {escape_md(f'{top10_pct:.1f}%')} \\({label}\\)"]

    lines += ["", "📝 *CONTRACT ADDRESS* \\(Tap to Copy\\)", f"`{ca}`"]

    socials_line = _social_links_line(pair)
    if socials_line:
        lines += ["", socials_line]

    return "\n".join(lines)


def handle_data(chat_id, ca, message_id):
    if not ca or not CA_RE.fullmatch(ca):
        send_message(chat_id, "Usage: `/data <contract address>`", message_id)
        return
    pair = fetch_best_pair(ca)
    if not pair:
        send_message(chat_id, f"❌ No pair found for `{escape_md(truncate_ca(ca))}`", message_id)
        return

    caption = _build_token_message(pair, ca)
    keyboard = _trade_keyboard(ca)
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


def handle_update(update: dict):
    message = update.get("message")
    if not message:
        return

    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()
    message_id = message["message_id"]
    user = message.get("from") or {}

    if text.startswith("/start"):
        send_message(chat_id, START_MESSAGE, message_id)
    elif text == "/ping":
        send_message(chat_id, "🏓 Pong\\! WaveScan is alive\\.", message_id)
    elif text.startswith("/data"):
        ca = text[len("/data"):].strip() or find_ca((message.get("reply_to_message") or {}).get("text", ""))
        handle_data(chat_id, ca, message_id)
    elif text.startswith("/alert") and not text.startswith("/alerts"):
        handle_alert(chat_id, text, message_id, user)
    elif text == "/alerts":
        handle_list_alerts(chat_id, user.get("id"), message_id)
    elif text.startswith("/cancel"):
        handle_cancel(chat_id, text, message_id, user)
    elif CA_RE.fullmatch(text):
        handle_data(chat_id, text, message_id)
