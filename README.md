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

## Deploy on Render (Blueprint)

1. Push this folder to a GitHub repo.
2. In Render, click **New → Blueprint** and point it at the repo. `render.yaml`
   defines two services:
   - **wavescan-bot** — the web service that receives Telegram webhook updates
   - **wavescan-alert-sweep** — a Cron Job that checks pending alerts every 2 minutes
3. Set the environment variables Render prompts for (shared across both services):
   - `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
   - `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` — from an [Upstash](https://upstash.com) Redis database (free tier is fine; this is where alerts are stored). If you skip this, `/data` and `/ping` still work, but `/alert` will tell users alerts aren't configured.
4. Once the web service is live, point Telegram at it:
   ```
   https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<your-service>.onrender.com/webhook
   ```
5. Message the bot `/ping` to confirm it's alive.

## Notes

- Render's free web-service tier spins down after inactivity, which adds a
  cold-start delay to the first message after idle. The Cron Job is
  unaffected since Render runs it directly on schedule.
- The sweep script groups alerts by contract address so a token with several
  pending alerts only costs one Dexscreener + one DexPaprika call per sweep.
