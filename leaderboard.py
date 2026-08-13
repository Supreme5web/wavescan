"""Group leaderboard, backed by Supabase (PostgREST) — no supabase-py
dependency, same lightweight requests-based style as storage.py.

Every time someone looks up a token in a group chat, we log one row per
(chat, user, ca) with the market cap at call time. A periodic sweep then
ratchets `best_mc` up as the token's live market cap rises, so `/leaderboard`
can rank callers by best_mc / entry_mc without hitting the market API itself.

Expected Supabase table (run once in the SQL editor):

    create table calls (
        id bigserial primary key,
        chat_id bigint not null,
        user_id bigint not null,
        username text,
        first_name text,
        ca text not null,
        symbol text,
        chain_id text,
        entry_mc numeric not null,
        best_mc numeric not null,
        multiple numeric generated always as (best_mc / entry_mc) stored,
        called_at timestamptz not null default now(),
        unique (chat_id, user_id, ca)
    );
    create index calls_chat_id_idx on calls (chat_id);
"""
import requests

from config import SUPABASE_URL, SUPABASE_KEY

_TIMEOUT = 8


def available() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def _headers(prefer: str = None) -> dict:
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def record_call(chat_id, user: dict, ca: str, symbol: str, chain_id: str, mc: float) -> bool:
    """Log a user's first call on this CA in this chat. Later calls on the
    same (chat, user, ca) are no-ops thanks to the unique constraint +
    ignore-duplicates — entry_mc is fixed at first sight; update_best()
    handles every rise after that."""
    if not available() or not mc:
        return False
    row = {
        "chat_id": chat_id,
        "user_id": user.get("id"),
        "username": user.get("username"),
        "first_name": user.get("first_name"),
        "ca": ca,
        "symbol": symbol,
        "chain_id": chain_id,
        "entry_mc": mc,
        "best_mc": mc,
    }
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/calls?on_conflict=chat_id,user_id,ca",
            headers=_headers("resolution=ignore-duplicates,return=minimal"),
            json=row,
            timeout=_TIMEOUT,
        )
        return r.ok
    except Exception as err:
        print("leaderboard record_call failed:", err)
        return False


def distinct_targets():
    """(chat_id, ca) pairs with at least one logged call, for the sweep to refresh."""
    if not available():
        return []
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/calls",
            headers=_headers(),
            params={"select": "chat_id,ca"},
            timeout=_TIMEOUT,
        )
        rows = r.json() if r.ok else []
        return sorted({(row["chat_id"], row["ca"]) for row in rows})
    except Exception as err:
        print("leaderboard distinct_targets failed:", err)
        return []


def update_best(chat_id, ca: str, mc: float) -> None:
    """Ratchet best_mc up (single request, all callers on this ca at once)."""
    if not available() or not mc:
        return
    try:
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/calls",
            headers=_headers("return=minimal"),
            params={"chat_id": f"eq.{chat_id}", "ca": f"eq.{ca}", "best_mc": f"lt.{mc}"},
            json={"best_mc": mc},
            timeout=_TIMEOUT,
        )
    except Exception as err:
        print("leaderboard update_best failed:", err)


def top_callers(chat_id, limit: int = 10):
    """Each user's single best call in this chat, ranked by multiplier desc."""
    if not available():
        return []
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/calls",
            headers=_headers(),
            params={
                "chat_id": f"eq.{chat_id}",
                "select": "user_id,username,first_name,ca,symbol,entry_mc,best_mc",
                "order": "multiple.desc",
                "limit": 50,
            },
            timeout=_TIMEOUT,
        )
        rows = r.json() if r.ok else []
    except Exception as err:
        print("leaderboard top_callers failed:", err)
        return []

    best_per_user = {}
    for row in rows:
        best_per_user.setdefault(row["user_id"], row)  # first hit per user = their best (rows are pre-sorted)
    return list(best_per_user.values())[:limit]
