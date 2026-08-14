"""Checks pending alerts and refreshes the leaderboard using Solana Tracker."""

from collections import defaultdict

import leaderboard
import storage
from config import TRADING_BOTS
from market import fetch_best_pair, get_market_cap
from telegram import send_message
from utils import escape_md, format_usd_short


def _mention(record: dict) -> str:
    if record.get("username"):
        return f"@{escape_md(record['username'])}"
    label = escape_md(record.get("firstName") or "trader")
    return f"[{label}](tg://user?id={record['userId']})"


def _ping(record: dict, symbol: str):
    links = " • ".join(f"[{label}]({build(record['ca'])})" for label, build in TRADING_BOTS)
    text = "\n".join([
        f"Yo\\! {_mention(record)}",
        "",
        f"*${escape_md(symbol)}* has reached {escape_md(format_usd_short(record['targetMc']))} mc",
        "",
        links,
    ])
    send_message(record["chatId"], text)


def _sweep_alerts():
    if not storage.available():
        print("KV not configured, skipping alerts")
        return {"checked": 0, "triggered": 0}

    keys = storage.keys("alert:*")
    if not keys:
        print("No pending alerts")
        return {"checked": 0, "triggered": 0}

    by_ca = defaultdict(list)
    for key in keys:
        record = storage.get_json(key)
        if record and record.get("ca"):
            by_ca[record["ca"]].append((key, record))

    checked = triggered = 0
    for ca, entries in by_ca.items():
        checked += len(entries)
        pair = fetch_best_pair(ca)
        if not pair:
            continue

        mc = get_market_cap(pair)
        symbol = ((pair.get("baseToken") or {}).get("symbol") or "UNKNOWN").upper()

        for key, record in entries:
            if mc >= record["targetMc"]:
                try:
                    _ping(record, symbol)
                except Exception as err:
                    print(f"Alert ping failed for {key}:", err)
                storage.delete_key(key)
                triggered += 1

    return {"checked": checked, "triggered": triggered}


def _mention_call(row: dict) -> str:
    if row.get("username"):
        return f"[@{escape_md(row['username'])}](https://t.me/{row['username']})"
    label = escape_md(row.get("first_name") or "trader")
    return f"[{label}](tg://user?id={row['user_id']})"


def _send_2x_alert(chat_id, row: dict, symbol: str, mult: float):
    text = "\n".join([
        "🚀 *2X CALL\\!*",
        f"{_mention_call(row)} called *${escape_md(symbol)}* — now *{escape_md(f'{mult:.1f}x')}* 🔥",
    ])
    send_message(chat_id, text, reply_to=row.get("message_id"))


def _sweep_leaderboard():
    if not leaderboard.available():
        return {"lb_checked": 0}

    targets = leaderboard.distinct_targets()
    if not targets:
        return {"lb_checked": 0}

    pair_cache = {}
    checked = 0
    for chat_id, ca in targets:
        checked += 1
        if ca not in pair_cache:
            pair_cache[ca] = fetch_best_pair(ca)
        pair = pair_cache[ca]
        if not pair:
            continue
        mc = get_market_cap(pair)
        if not mc:
            continue

        symbol = ((pair.get("baseToken") or {}).get("symbol") or "UNKNOWN").upper()
        for row in leaderboard.calls_for_target(chat_id, ca):
            entry_mc = float(row.get("entry_mc") or 0)
            if not entry_mc:
                continue
            old_mult = float(row.get("best_mc") or 0) / entry_mc
            new_mult = mc / entry_mc
            if new_mult >= 2 and old_mult < 2:
                try:
                    _send_2x_alert(chat_id, row, row.get("symbol") or symbol, new_mult)
                except Exception as err:
                    print(f"2x alert failed for chat={chat_id} ca={ca}:", err)

        leaderboard.update_best(chat_id, ca, mc)

    return {"lb_checked": checked}


def run():
    result = _sweep_alerts()
    result.update(_sweep_leaderboard())
    print(
        f"checked={result['checked']} triggered={result['triggered']} "
        f"lb_checked={result.get('lb_checked', 0)}"
    )
    return result


if __name__ == "__main__":
    run()
