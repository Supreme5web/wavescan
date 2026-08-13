"""Minimal public-RPC helpers for Solana holder analytics.

Only the two numbers WaveScan's /data card actually shows are computed here:
holder count and top-10 concentration (with the presumed LP/vault dropped).
Both degrade to None on any failure so the card just omits that line rather
than showing a wrong number — public RPC can be slow or rate-limited.
"""
import base64
import struct

import requests

from config import SOLANA_RPC_URL, TOKEN_PROGRAM_ID


def _rpc(method: str, params: list, timeout: int = 12):
    try:
        r = requests.post(
            SOLANA_RPC_URL,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=timeout,
        )
        data = r.json()
        if "error" in data:
            print(f"Solana RPC error ({method}):", data["error"])
            return None
        return data.get("result")
    except Exception as err:
        print(f"Solana RPC call failed ({method}):", err)
        return None


def get_token_supply(mint: str):
    result = _rpc("getTokenSupply", [mint])
    return result.get("value") if result else None


def get_largest_accounts(mint: str):
    result = _rpc("getTokenLargestAccounts", [mint])
    return result.get("value") if result else None


def get_top10_concentration(mint: str):
    """% of supply held by the top 10 holders, excluding the presumed LP/vault
    (rank 1 on a live pool is virtually always the pool itself)."""
    supply = get_token_supply(mint)
    largest = get_largest_accounts(mint)
    if not supply or not largest:
        return None
    total = float(supply.get("uiAmount") or 0)
    if not total:
        return None
    ranked = sorted(largest, key=lambda a: float(a.get("amount") or 0), reverse=True)
    top10 = ranked[1:11]
    return sum(float(a.get("uiAmount") or 0) / total * 100 for a in top10)


def get_holder_count(mint: str, timeout: int = 12):
    """Count of token accounts for this mint with a non-zero balance.

    Uses dataSlice to fetch only the 8-byte amount field per account (offset
    64 in the SPL token account layout) instead of full account bodies —
    keeps the response small even for tokens with a lot of holders.
    """
    result = _rpc(
        "getProgramAccounts",
        [
            TOKEN_PROGRAM_ID,
            {
                "encoding": "base64",
                "filters": [
                    {"dataSize": 165},
                    {"memcmp": {"offset": 0, "bytes": mint}},
                ],
                "dataSlice": {"offset": 64, "length": 8},
            },
        ],
        timeout=timeout,
    )
    if result is None:
        return None
    count = 0
    for entry in result:
        try:
            raw = base64.b64decode(entry["account"]["data"][0])
            if struct.unpack("<Q", raw)[0] > 0:
                count += 1
        except Exception:
            continue
    return count
