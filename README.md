# WaveScan

A lean Telegram bot for token lookups and market-cap alerts. Market/token data comes exclusively from Solana Tracker. Holder analytics still use the configured Solana RPC. No Dexscreener or DexPaprika market-data calls are used.

## Commands

- Send a bare Solana contract address — fetch price, market cap, liquidity, volume and token info. The card has two buttons: 🔄 **Refresh** and 🗑️ **Delete**.
- `/alert <ca> <target mc>` — get pinged when a token hits a target market cap (`500k`, `1.2m`, `900000` all work)
- `/alerts` — list your active alerts in this chat
- `/cancel <ca>` — cancel an alert
- `/leaderboard` (or `/lb`) — in groups, ranks callers by the best multiplier (peak mc ÷ mc at time of call) any of their calls has reached
- `/ping` — liveness check
- Pasting a bare contract address scans it directly and — in groups — logs it as a call for the leaderboard

## Deploy on Render — single free Web Service

Render doesn't offer a free tier for Cron Jobs (`starter` plan minimum), so
the default setup here is a single free **Web Service** with alerts checked
via an HTTP endpoint you trigger externally, instead of a paid Render cron.

1. Push this folder to a GitHub repo.
2. In Render, **New → Web Service**, point it at the repo (or **New → Blueprint**
   to use `render.yaml` directly — same result, one service either way).
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app`
3. Set environment variables:
   - `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
   - `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` — from an [Upstash](https://upstash.com) Redis database (free tier is fine; this is where alerts are stored). Without these, bare CA lookups and `/ping` still work, but `/alert` will tell users alerts aren't configured.
   - `CRON_SECRET` — any random string you make up, so strangers can't trigger your sweep endpoint.
   - `SOLANATRACKER_API_KEY` — from [Solana Tracker](https://www.solanatracker.io/account). Used for token market data, timeframe stats, holders, and ATH data.
   - `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` — from a [Supabase](https://supabase.com) project (Project Settings → API; use the **service_role** key, not `anon`, since the bot writes from the server). Without these, everything else still works, but `/leaderboard` will tell users it isn't configured. Run this once in the Supabase SQL editor first:
     ```sql
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
         message_id bigint,
         multiple numeric generated always as (best_mc / entry_mc) stored,
         called_at timestamptz not null default now(),
         unique (chat_id, user_id, ca)
     );
     create index calls_chat_id_idx on calls (chat_id);
     ```
     Upgrading an existing table? Just run `alter table calls add column message_id bigint;`
4. Once the service is live, point Telegram at it:
   ```
   https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<your-service>.onrender.com/webhook
   ```
5. Set up alert checking: use a free external scheduler (e.g. [cron-job.org](https://cron-job.org))
   to hit this URL every 1–2 minutes:
   ```
   https://<your-service>.onrender.com/sweep?secret=<CRON_SECRET>
   ```
   This also happens to keep the free web service warm, avoiding cold-start
   delays on Telegram messages.
6. Message the bot `/ping` to confirm it's alive.

## Alternative: Render Cron Job (paid)

If you'd rather not depend on a third-party scheduler, add a second service
to `render.yaml`:

```yaml
  - type: cron
    name: wavescan-alert-sweep
    env: python
    plan: starter          # cron has no free tier on Render
    schedule: "*/2 * * * *"
    buildCommand: pip install -r requirements.txt
    startCommand: python sweep.py
    envVars:
      - key: TELEGRAM_BOT_TOKEN
        sync: false
      - key: UPSTASH_REDIS_REST_URL
        sync: false
      - key: UPSTASH_REDIS_REST_TOKEN
        sync: false
```

`sweep.py` still runs standalone via `python sweep.py`, so this drops in
without touching any other file.

## Notes

- The sweep groups alerts by contract address so a token with several
  pending alerts only requires one Solana Tracker token lookup per run.
- The same sweep also refreshes the leaderboard: it ratchets each tracked
  call's `best_mc` up using the live market cap (not an OHLCV lookback like
  alerts do), so a spike that fully reverses between two sweeps can be
  under-counted. Running the sweep every 1–2 minutes keeps that gap small.
