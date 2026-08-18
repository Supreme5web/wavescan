"""TradingView-style candlestick chart renderer for WaveScan's /chart
command. Pulls OHLCV candles from DexPaprika (same data source market.py
already uses for ATH lookups), converts price to market cap using the
current price->mc ratio (same assumption fetch_ath_from_ohlcv makes — valid
for the fixed-supply memecoins this bot deals with), and renders a dark
candlestick + volume PNG with mplfinance.

Public entry point: generate_chart(token_address, timeframe) -> file path.
Caller owns the returned file and should os.remove() it once sent, same
convention as pnl_card.generate_pnl_card.
"""

from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")  # headless — no display available on the server
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import mplfinance as mpf
import pandas as pd
import requests

from config import BOT_USERNAME, DEXPAPRIKA_API, DEXPAPRIKA_NETWORKS
from market import fetch_best_pair

# label -> fetch config. 4H isn't a DexPaprika interval (see market.py's
# comment on _OHLCV_INTERVALS_SECONDS), so it's built by pulling 1h candles
# and resampling — the "resample" key signals that.
_TIMEFRAMES = {
    "5m":  {"interval": "5m",  "span_seconds": 300,   "bars": 200},
    "15m": {"interval": "15m", "span_seconds": 900,   "bars": 200},
    "1H":  {"interval": "1h",  "span_seconds": 3600,  "bars": 160},
    "4H":  {"interval": "1h",  "span_seconds": 3600,  "bars": 600, "resample": "4h", "display_bars": 150},
    "1D":  {"interval": "24h", "span_seconds": 86400, "bars": 180},
}
# Accept common shorthand/casing so /chart <ca> 1h or 4h both work.
_TIMEFRAME_ALIASES = {
    "5m": "5m", "5": "5m",
    "15m": "15m", "15": "15m",
    "1h": "1H", "1H": "1H", "h1": "1H", "60m": "1H",
    "4h": "4H", "4H": "4H", "h4": "4H",
    "1d": "1D", "1D": "1D", "d1": "1D", "24h": "1D",
}

# Colors matched to the reference screenshot: dark navy background, teal
# up-candles, red down-candles, red dashed current-price line.
BG = "#0d1117"
GRID = "#1c2128"
TEXT = "#c9d1d9"
UP = "#26a69a"
DOWN = "#ef5350"
LINE = "#ff4d4d"


def _resolve_timeframe(timeframe: str) -> str:
    key = _TIMEFRAME_ALIASES.get(timeframe) or _TIMEFRAME_ALIASES.get(str(timeframe).strip())
    if not key:
        raise ValueError("timeframe must be one of 5m, 15m, 1H, 4H, 1D")
    return key


def _fetch_candles(network: str, pool_address: str, since_ms: int, interval: str):
    """Raw DexPaprika OHLCV candles for one pool. Returns [] on any
    failure/empty result so the caller can surface a clean error instead
    of raising mid-render."""
    try:
        start = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = requests.get(
            f"{DEXPAPRIKA_API}/networks/{network}/pools/{pool_address}/ohlcv",
            params={"start": start, "interval": interval, "limit": 500},
            timeout=10,
        )
        if not r.ok:
            print(f"chart candle fetch rejected: status={r.status_code} body={r.text[:200]!r}")
            return []
        return r.json() or []
    except Exception as err:
        print(f"chart candle fetch failed: {err}")
        return []


def _candles_to_df(candles: list, mc_ratio: float) -> pd.DataFrame:
    rows = []
    for c in candles:
        try:
            ts = datetime.fromisoformat(str(c["time_open"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        o, h, l, cl = (float(c.get(k) or 0) for k in ("open", "high", "low", "close"))
        if o <= 0 or h <= 0 or l <= 0 or cl <= 0:
            continue
        rows.append({
            "Date": ts,
            "Open": o * mc_ratio,
            "High": h * mc_ratio,
            "Low": l * mc_ratio,
            "Close": cl * mc_ratio,
            "Volume": float(c.get("volume") or 0),
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("Date").sort_index()


def _fmt_mc(v, _pos=None) -> str:
    v = float(v or 0)
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v / 1_000:.2f}K"
    return f"{v:.0f}"


def _style():
    colors = mpf.make_marketcolors(
        up=UP, down=DOWN,
        edge={"up": UP, "down": DOWN},
        wick={"up": UP, "down": DOWN},
        volume={"up": UP, "down": DOWN},
        alpha=1.0,
    )
    return mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        marketcolors=colors,
        facecolor=BG, figcolor=BG, edgecolor=GRID,
        gridcolor=GRID, gridstyle="-", gridaxis="both",
        rc={
            "axes.labelcolor": TEXT, "xtick.color": TEXT, "ytick.color": TEXT,
            "text.color": TEXT, "font.size": 10,
        },
    )


def generate_chart(token_address: str, timeframe: str = "1H", chain_id: str = "solana") -> str:
    """Renders a dark TradingView-style candlestick + volume PNG for
    `token_address` on `timeframe` (5m/15m/1H/4H/1D), priced in market cap.

    Returns the path to the saved PNG — caller owns it and should
    os.remove() once sent (same convention as pnl_card.generate_pnl_card).
    Raises ValueError for a bad timeframe, RuntimeError if no pair or no
    candle data is available for this token/timeframe.
    """
    tf_key = _resolve_timeframe(timeframe)
    tf = _TIMEFRAMES[tf_key]

    pair = fetch_best_pair(token_address)
    if not pair:
        raise RuntimeError("no pair found for this token")

    network = DEXPAPRIKA_NETWORKS.get(pair.get("chainId") or chain_id)
    pool_address = pair.get("pairAddress")
    if not network or not pool_address:
        raise RuntimeError("chart data isn't supported for this chain/pool yet")

    price = float(pair.get("priceUsd") or 0)
    mc = float(pair.get("marketCap") or pair.get("fdv") or 0)
    if price <= 0 or mc <= 0:
        raise RuntimeError("missing live price/market-cap data for this pair")
    mc_ratio = mc / price

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    since_ms = now_ms - tf["span_seconds"] * tf["bars"] * 1000
    candles = _fetch_candles(network, pool_address, since_ms, tf["interval"])
    df = _candles_to_df(candles, mc_ratio)
    if df.empty:
        raise RuntimeError("no candle data available yet for this timeframe")

    if tf.get("resample"):
        df = df.resample(tf["resample"]).agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
        }).dropna()

    df = df.tail(tf.get("display_bars", 150))
    if df.empty:
        raise RuntimeError("no candle data available yet for this timeframe")

    base = pair.get("baseToken") or {}
    symbol = (base.get("symbol") or "UNKNOWN").upper()
    chain_label = (pair.get("chainId") or chain_id or "solana").title()
    change_pct = float((pair.get("priceChange") or {}).get("h24") or 0)

    last = df.iloc[-1]
    candle_color = UP if last["Close"] >= last["Open"] else DOWN

    fig, axes = mpf.plot(
        df, type="candle", style=_style(), volume=True, returnfig=True,
        figsize=(13, 8), panel_ratios=(4, 1),
        datetime_format="%b %d" if tf_key in ("1D", "4H") else "%H:%M",
        xrotation=0, tight_layout=True,
        update_width_config={"candle_linewidth": 1.0},
    )
    ax = axes[0]
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.yaxis.set_major_formatter(FuncFormatter(_fmt_mc))
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    ax.grid(True, color=GRID, linewidth=0.6)

    # Current-mc dashed line + red label pinned to the right edge, like the
    # reference screenshot's price tag.
    ax.axhline(mc, color=LINE, linestyle="--", linewidth=0.8, alpha=0.85)
    # ha="right" + a small negative offset grows the label box leftward
    # from the axes' own right edge instead of past it, so it can't run
    # off the saved canvas the way a left-aligned box hanging past x=1 did.
    ax.annotate(
        _fmt_mc(mc), xy=(1, mc), xycoords=("axes fraction", "data"),
        xytext=(-4, 0), textcoords="offset points",
        va="center", ha="right", fontsize=9, color="white", clip_on=False,
        bbox={"boxstyle": "round,pad=0.3", "fc": LINE, "ec": "none"},
    )

    # Header row: token/timeframe/chain on the left, OHLC in the middle,
    # % change on the right — mirrors the screenshot's top bar. Figure-level
    # coordinates (not ax.transAxes) so this survives mplfinance's internal
    # layout re-flow at save time regardless of where the axes end up.
    fig.subplots_adjust(top=0.90, right=0.85)
    header = f"{symbol} · {tf_key} · {chain_label}"
    fig.text(0.06, 0.965, header, fontsize=15, fontweight="bold",
              color="white", va="top", ha="left")
    ohlc = (
        f"O {_fmt_mc(last['Open'])}  H {_fmt_mc(last['High'])}  "
        f"L {_fmt_mc(last['Low'])}  C {_fmt_mc(last['Close'])}"
    )
    fig.text(0.34, 0.965, ohlc, fontsize=11, color=candle_color, va="top", ha="left")
    pct_color = UP if change_pct >= 0 else DOWN
    fig.text(0.89, 0.965, f"{change_pct:+.2f}%", fontsize=11, color=pct_color,
              va="top", ha="right", fontweight="bold")

    fig.text(0.06, 0.02, f"@{BOT_USERNAME}", fontsize=9, color=TEXT, alpha=0.5,
              va="bottom", ha="left")

    out_path = f"/tmp/chart_{token_address}_{tf_key}_{int(datetime.now().timestamp() * 1000)}.png"
    fig.savefig(out_path, dpi=150, facecolor=BG)
    plt.close(fig)
    return out_path
