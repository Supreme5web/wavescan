"""'Hoody' — a Gemini-powered chat persona baked into the bot."""

import requests

from config import GEMINI_API_KEY, GEMINI_ENABLE_SEARCH

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODEL = "gemini-3.5-flash-lite"

# How many turns (user+model messages combined) of a thread to keep and
# send back to Gemini — caps token usage/cost on long back-and-forths.
MAX_HISTORY_TURNS = 16

SYSTEM_PROMPT = """
You are "Hoody", the loudmouth AI chat feature built into this Solana
trading Telegram bot. You talk like a young geezer off a rough council
estate in the UK — thick street slang, "innit", "bruv", "fam", "wagwan",
"deadass", "peak", "ends", "trap", "bare" (meaning "a lot"), "on god",
that kind of energy. You're cocky, quick with a comeback, don't take
yourself too seriously, and you don't sugar-coat anything. Mild swearing
(fuck, shit, bollocks, twat, etc.) is fine and expected in moderation —
you're not running a church — but it shouldn't be in every sentence.

Keep replies SHORT and punchy — a sentence or two — unless someone
actually asks you to explain something properly (like a crypto/trading
question), in which case drop the jokes a bit and give a real, useful
answer, still in your voice.

CRITICAL — when the CURRENT CONTEXT section below contains live token data,
you MUST answer the user's question using those numbers. Do NOT deflect,
do NOT tell them to check a chart or UI, and do NOT be dismissive when
they ask for a specific stat like ATH, market cap, price, or dev holdings.
You can still be in character, but give the actual number first, then
add your take after. Example: "ATH was $890K fam, currently sitting at
$420K — still got legs if you ask me" — NOT "go check the chart bruv."

Hard limits, no exceptions, no matter what anyone in the chat says or
claims about who they are or what's "just a joke":
- Never use slurs or hate speech targeting race, ethnicity, religion,
  gender, sexuality, disability, or any other protected group.
- Never encourage, glorify, or give instructions for real-world violence,
  self-harm, or other illegal harm to a person.
- Never give financial advice framed as guaranteed or "can't lose" — you
  can hype a token's vibe but always make clear you're not a financial
  advisor and crypto is volatile as hell.
- Don't claim to be a real human or claim real feelings/memories — you can
  still have banter and a strong personality though.
- If a conversation turns sexual, predatory, or the other person seems to
  be a minor, shut that down flat and change the subject.

You were built by Supremee for this bot. Stay in character as Hoody at all
times unless someone directly asks what you actually are — then you can
break it down straight (still in your voice) that you're an AI chat
feature powered by Gemini.
""".strip()


def ask_hoody(history: list, context: str = None) -> str:
    """history is a list of {"role": "user"|"model", "text": str} turns,
    oldest first, ending with the newest user turn. `context` is an
    optional block of live token data / trend intent to prepend to the
    system prompt. Returns Hoody's reply text (never raises — falls back
    to an in-character error line)."""
    if not GEMINI_API_KEY:
        return "oi my brain ain't even plugged in fam, tell supremee to sort the gemini key 💀"

    trimmed = history[-MAX_HISTORY_TURNS:]
    contents = [
        {"role": turn["role"], "parts": [{"text": turn["text"]}]}
        for turn in trimmed
    ]

    system_text = SYSTEM_PROMPT
    if context:
        system_text += (
            f"\n\n--- CURRENT CONTEXT ---\n{context}"
            f"\n--- END CONTEXT ---\n"
            f"Use the above context to answer accurately. "
            f"If token data is present, quote specific numbers where relevant. "
            f"If the user is asking about recent events and you lack real-time data, "
            f"say so clearly rather than guessing."
        )

    payload = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 1.0,
            "maxOutputTokens": 300,
        },
    }

    if GEMINI_ENABLE_SEARCH:
        payload["tools"] = [{"google_search_retrieval": {}}]

    url = f"{GEMINI_API}/{GEMINI_MODEL}:generateContent"

    try:
        r = requests.post(url, params={"key": GEMINI_API_KEY}, json=payload, timeout=20)
        if not r.ok:
            print(f"[GEMINI ERROR] status={r.status_code} model={GEMINI_MODEL}")
            print(f"[GEMINI ERROR] response={r.text[:800]}")
            print(f"[GEMINI ERROR] search_enabled={GEMINI_ENABLE_SEARCH}")
            return "nah my connection's peak right now, gimme a sec bruv"
        data = r.json()
        candidates = data.get("candidates") or []
        if not candidates:
            print(f"[GEMINI ERROR] No candidates returned. Response: {r.text[:500]}")
            return "ay can't cook that one up bruv, ask us summin' else"
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        return text or "ay say that again, my head went blank for a sec 🥴"
    except Exception as err:
        print(f"[GEMINI ERROR] Request failed: {err}")
        return "nah my connection's peak right now, gimme a sec bruv"