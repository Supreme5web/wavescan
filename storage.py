import json
import requests

from config import KV_URL, KV_TOKEN

_TIMEOUT = 6


def available() -> bool:
    return bool(KV_URL and KV_TOKEN)


def _headers():
    return {"Authorization": f"Bearer {KV_TOKEN}"}


def get_json(key: str):
    if not available():
        return None
    try:
        r = requests.get(f"{KV_URL}/get/{key}", headers=_headers(), timeout=_TIMEOUT)
        raw = r.json().get("result")
        return json.loads(raw) if raw else None
    except Exception as err:
        print("KV get failed:", err)
        return None


def set_json(key: str, obj) -> bool:
    if not available():
        return False
    try:
        r = requests.post(f"{KV_URL}/set/{key}", headers=_headers(), data=json.dumps(obj), timeout=_TIMEOUT)
        return r.ok
    except Exception as err:
        print("KV set failed:", err)
        return False


def delete_key(key: str) -> bool:
    if not available():
        return False
    try:
        requests.get(f"{KV_URL}/del/{key}", headers=_headers(), timeout=_TIMEOUT)
        return True
    except Exception as err:
        print("KV delete failed:", err)
        return False


def keys(pattern: str):
    if not available():
        return []
    try:
        r = requests.get(f"{KV_URL}/keys/{pattern}", headers=_headers(), timeout=8)
        result = r.json().get("result")
        return result if isinstance(result, list) else []
    except Exception as err:
        print("KV keys scan failed:", err)
        return []
