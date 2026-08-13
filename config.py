import os

BOT_NAME = "WaveScan"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Optional: set CRON_SECRET so the sweep can't be triggered by strangers if
# you ever expose it over HTTP instead of running it as a Render Cron Job.
CRON_SECRET = os.environ.get("CRON_SECRET")

# Upstash Redis (REST) — used as the alert store.
KV_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
KV_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")

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
    ("AXI", lambda ca: f"https://axiom.trade/t/{ca}"),
    ("TRO", lambda ca: f"https://t.me/menelaus_trojanbot?start=r-{ca}"),
    ("GMGN", lambda ca: f"https://gmgn.ai/sol/token/{ca}"),
]

# Public Solana RPC (no API key) — used only for holder-count / top-10
# concentration on Solana tokens, since Dexscreener/DexPaprika don't expose that.
SOLANA_RPC_URL = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
