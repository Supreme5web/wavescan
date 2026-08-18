"""'Hoody' — a Gemini-powered chat persona baked into the bot.

Triggered whenever someone's message mentions "hoody" by name, and keeps
the thread going if someone replies directly to one of Hoody's own
messages (see bot.py's handle_hoody / _hoody_key for the reply-threading
side of this).
"""

import requests

from config import GEMINI_API_KEY

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


def ask_hoody(history: list) -> str:
    """history is a list of {"role": "user"|"model", "text": str} turns,
    oldest first, ending with the newest user turn. Returns Hoody's reply
    text (never raises — falls back to an in-character error line)."""
    if not GEMINI_API_KEY:
        return "oi my brain ain't even plugged in fam, tell supremee to sort the gemini key 💀"

    trimmed = history[-MAX_HISTORY_TURNS:]
    contents = [
        {"role": turn["role"], "parts": [{"text": turn["text"]}]}
        for turn in trimmed
    ]

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 1.0,
            "maxOutputTokens": 300,
        },
    }

    try:
        r = requests.post(
            f"{GEMINI_API}/{GEMINI_MODEL}:generateContent",
            params={"key": GEMINI_API_KEY},
            json=payload,
            timeout=20,
        )
        if not r.ok:
            print("Gemini request rejected:", r.status_code, r.text[:300])
            return "nah my connection's peak right now, gimme a sec bruv"
        data = r.json()
        candidates = data.get("candidates") or []
        if not candidates:
            # Usually means the safety filters blocked it outright.
            return "ay can't cook that one up bruv, ask us summin' else"
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        return text or "ay say that again, my head went blank for a sec 🥴"
    except Exception as err:
        print("Gemini request failed:", err)
        return "nah my connection's peak right now, gimme a sec bruv"
