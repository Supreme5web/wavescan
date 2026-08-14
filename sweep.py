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
        if mc:
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
