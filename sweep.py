"""Checks all pending alerts and pings users whose target market cap has
been reached. Meant to run periodically as a Render Cron Job (see render.yaml)."""
import time
from collections import defaultdict

import leaderboard
import storage
from config import TRADING_BOTS
from market import fetch_best_pair, fetch_peak_price, get_market_cap
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

    # Group by CA so a token with several pending alerts is only fetched once.
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
            continue  # leave pending, retry next sweep

        price = float(pair.get("priceUsd") or 0)
        mc = get_market_cap(pair)
        symbol = ((pair.get("baseToken") or {}).get("symbol") or "UNKNOWN").upper()

        peak_mc = mc
        pool, chain = pair.get("pairAddress"), pair.get("chainId")
        if price > 0 and mc > 0 and pool:
            earliest = min(rec.get("createdAt", int(time.time() * 1000)) for _, rec in entries)
            peak_price = fetch_peak_price(chain, pool, earliest)
            if peak_price > 0:
                peak_mc = max(peak_mc, peak_price * (mc / price))

        for key, record in entries:
            if peak_mc >= record["targetMc"] or mc >= record["targetMc"]:
                try:
                    _ping(record, symbol)
                except Exception as err:
                    print(f"Alert ping failed for {key}:", err)
                storage.delete_key(key)  # remove regardless, so a stuck chat can't retry forever
                triggered += 1

    return {"checked": checked, "triggered": triggered}


def _sweep_leaderboard():
    """Ratchets best_mc up for every tracked group call, so /leaderboard
    stays current without hitting the market API on every request."""
    if not leaderboard.available():
        return {"lb_checked": 0}

    targets = leaderboard.distinct_targets()
    if not targets:
        return {"lb_checked": 0}

    pair_cache = {}  # a CA called in several chats only gets fetched once
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
    print(f"checked={result['checked']} triggered={result['triggered']} lb_checked={result.get('lb_checked', 0)}")
    return result


if __name__ == "__main__":
    run()
