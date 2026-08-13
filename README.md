# WaveScan

A lean Telegram bot for token lookups and market-cap alerts. Data comes from
[Dexscreener](https://dexscreener.com) (live price/liquidity/volume) and
[DexPaprika](https://dexpaprika.com) (hourly OHLCV history, used only to catch
price spikes that already receded between two alert sweeps). No Codex, no
Helius, no RPC calls, no image rendering — just the two commands that matter.

## Commands

- `/data <ca>` — price, market cap, liquidity, 24h volume for a token
- `/alert <ca> <target mc>` — get pinged when a token hits a target market cap (`500k`, `1.2m`, `900000` all work)
- `/alerts` — list your active alerts in this chat
- `/cancel <ca>` — cancel an alert
- `/ping` — liveness check
- Pasting a bare contract address also runs `/data` on it

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
   - `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` — from an [Upstash](https://upstash.com) Redis database (free tier is fine; this is where alerts are stored). Without these, `/data` and `/ping` still work, but `/alert` will tell users alerts aren't configured.
   - `CRON_SECRET` — any random string you make up, so strangers can't trigger your sweep endpoint.
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
  pending alerts only costs one Dexscreener + one DexPaprika call per run,
  whether triggered by `/sweep` or the standalone script.
