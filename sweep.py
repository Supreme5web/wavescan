"""Checks pending alerts and refreshes the leaderboard using Solana Tracker."""

from collections import defaultdict

import dexscreener
import leaderboard
import storage
from config import TRADING_BOTS
from market import fetch_best_pair, get_market_cap
from telegram import send_message
from utils import escape_md, format_usd_short


# Milestones that trigger a group alert when a call's multiplier crosses them.
_MILESTONES = [2, 5, 10, 20, 30, 50, 100]


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


def _send_milestone_alert(chat_id, row: dict, symbol: str, milestone: int):
    text = "\n".join([
        f"🚀 *{milestone}X CALL\\!*",
        f"{_mention_call(row)} called *${escape_md(symbol)}* — now *{escape_md(f'{milestone}x')}* 🔥",
    ])
    send_message(chat_id, text, reply_to=row.get("message_id"))


def _check_milestones(chat_id, row: dict, symbol: str, old_mult: float, new_mult: float):
    """Fire an alert for every milestone the call just crossed for the first time."""
    for m in _MILESTONES:
        if new_mult >= m and old_mult < m:
            try:
                _send_milestone_alert(chat_id, row, symbol, m)
            except Exception as err:
                print(f"Milestone alert failed for chat={chat_id} ca={row.get('ca')} milestone={m}x:", err)


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
            _check_milestones(chat_id, row, row.get("symbol") or symbol, old_mult, new_mult)

        leaderboard.update_best(chat_id, ca, mc)

    return {"lb_checked": checked}


def fast_refresh_ath():
    """Lightweight best_mc (per-caller PNL) ratchet, meant to run every ~10s
    from a background thread (see app.py) — NOT the full leaderboard sweep.

    Uses Dexscreener instead of Solana Tracker because it's cheap/fast
    enough to poll this often, so this stays fast. This is what keeps
    /pnl accurate even if nobody has re-run /data since the token was
    first called. (The card's *token* ATH display is a separate concern,
    handled in bot.py via market.fetch_ath_from_ohlcv — real historical
    candles, not this loop.)

    IMPORTANT: this also has to own the milestone-crossing alerts. Since
    this loop ratchets best_mc every 10s, by the time the slower `/sweep`
    cron runs best_mc is usually already past the lower milestones, so
    its own crossing check would never fire — this loop sees the
    crossing first, so it has to be the one to send it.
    """
    if not leaderboard.available():
        return {"fast_checked": 0}

    targets = leaderboard.distinct_targets()
    if not targets:
        return {"fast_checked": 0}

    distinct_cas = [ca for _, ca in targets]
    mc_cache = dexscreener.fetch_market_caps_batch(distinct_cas)
    checked = 0
    for chat_id, ca in targets:
        checked += 1
        mc = mc_cache.get(ca)
        if not mc:
            continue

        for row in leaderboard.calls_for_target(chat_id, ca):
            entry_mc = float(row.get("entry_mc") or 0)
            if not entry_mc:
                continue
            old_mult = float(row.get("best_mc") or 0) / entry_mc
            new_mult = mc / entry_mc
            symbol = row.get("symbol") or "UNKNOWN"
            _check_milestones(chat_id, row, symbol, old_mult, new_mult)

        leaderboard.update_best(chat_id, ca, mc)

    return {"fast_checked": checked}


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