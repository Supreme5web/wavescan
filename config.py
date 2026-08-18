import os

BOT_NAME = "HoodScan"

# Used to build the "jump to this bot" deep link in the /data footer.
BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "HoodScanBot")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Optional: set CRON_SECRET so the sweep can't be triggered by strangers if
# you ever expose it over HTTP instead of running it as a Render Cron Job.
CRON_SECRET = os.environ.get("CRON_SECRET")

# Upstash Redis (REST) — used as the alert store.
KV_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
KV_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")

# Supabase (PostgREST) — used as the group leaderboard store. Use the
# service_role key, not anon, since writes happen from the bot server.
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

DEXSCREENER_API = "https://api.dexscreener.com"
DEXPAPRIKA_API = "https://api.dexpaprika.com"

# Dexscreener chainId -> DexPaprika network slug, for OHLCV peak-price lookups.
DEXPAPRIKA_NETWORKS = {
    "solana": "solana",
    "ethereum": "ethereum",
    "bsc": "bsc",
    "base": "base",
    "arbitrum": "arbitrum",
    "polygon": "polygon",
    "avalanche": "avalanche",
}

# Quick-trade deep links shown under every token lookup / alert ping.
TRADING_BOTS = [
    ("AXI", lambda ca: f"https://axiom.trade/t/{ca}/@supremee5?chain=sol"),
    ("TRO", lambda ca: f"https://t.me/menelaus_trojanbot?start=d-supremeesol-{ca}"),
    ("BONK", lambda ca: f"https://t.me/bonkbot_bot?start=ref_ggydi_ca_{ca}"),
    ("MAE", lambda ca: f"https://t.me/maestro?start={ca}-hollydodson"),
    ("GMGN", lambda ca: f"https://gmgn.ai/sol/token/supremee5_{ca}"),
]

# Solana RPC — used only for holder-count / top-10 concentration on Solana
# tokens, since Dexscreener/DexPaprika don't expose that. Defaults to Helius
# (much higher rate limits than the public RPC) when HELIUS_API_KEY is set;
# falls back to the public RPC otherwise, or to SOLANA_RPC_URL if you set
# that explicitly (e.g. to point at a different provider).
HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY")
SOLANA_RPC_URL = os.environ.get("SOLANA_RPC_URL") or (
    f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
    if HELIUS_API_KEY
    else "https://api.mainnet-beta.solana.com"
)
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

# Solana Tracker Data API — used for accurate Solana token info + a real
# all-time-high (Solana Tracker tracks every indexed trade, so its /ath
# endpoint doesn't miss spikes the way a coarse OHLCV lookback can) and as
# a fallback market-cap source when Dexscreener hasn't populated fdv/marketCap
# yet (common for pairs that are only seconds/minutes old).
SOLANATRACKER_API = "https://data.solanatracker.io"
SOLANATRACKER_API_KEY = os.environ.get("SOLANATRACKER_API_KEY")

# Gemini — powers the "Hoody" AI chat persona (see gemini.py). Get a key at
# https://aistudio.google.com/apikey
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
