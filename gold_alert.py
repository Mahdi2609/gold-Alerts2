import os

import pandas as pd
import requests

# ---------- Settings ----------
SYMBOL = "GC=F"          # Gold futures on Yahoo Finance (close to XAUUSD)
INTERVAL_MIN = 15
LOOKBACK = 20            # swing high/low lookback (candles)
PIN_WICK_MIN = 0.30      # main wick must be at least 30% of the candle range
DOJI_BODY_MAX = 0.10     # body at most 10% of the candle range = doji


def send(text):
    token = os.environ["TELEGRAM_TOKEN"]
    chat = os.environ["TELEGRAM_CHAT_ID"]
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat, "text": text},
        timeout=20,
    )
    r.raise_for_status()


def detect(df):
    """df: closed candles with Open/High/Low/Close.
    Setup candle = df[-2] (pin bar or doji at swing low/high).
    Confirmation candle = df[-1] (closes beyond the whole setup candle).
    Returns dict or None."""
    if len(df) < LOOKBACK + 3:
        return None

    p = df.iloc[-2]   # setup candle
    c = df.iloc[-1]   # confirmation candle

    rng = p["High"] - p["Low"]
    if rng <= 0:
        return None

    body = abs(p["Close"] - p["Open"])
    upper = p["High"] - max(p["Open"], p["Close"])
    lower = min(p["Open"], p["Close"]) - p["Low"]

    is_doji = body <= DOJI_BODY_MAX * rng
    bull_pin = lower >= PIN_WICK_MIN * rng and lower > upper
    bear_pin = upper >= PIN_WICK_MIN * rng and upper > lower

    # swing low / swing high over the lookback window ending at the setup candle
    window = df.iloc[-2 - LOOKBACK + 1:-1]
    at_low = p["Low"] <= window["Low"].min()
    at_high = p["High"] >= window["High"].max()

    buy = at_low and (bull_pin or is_doji) and c["Close"] > c["Open"] and c["Close"] > p["High"]
    sell = at_high and (bear_pin or is_doji) and c["Close"] < c["Open"] and c["Close"] < p["Low"]

    if not (buy or sell):
        return None

    return {
        "side": "BUY" if buy else "SELL",
        "entry": float(c["Close"]),
        "setup": "Doji" if is_doji else "Pin bar",
        "time": df.index[-1],
    }


def main():
    if os.environ.get("TEST_MODE", "").lower() == "true":
        send("Test OK: gold alert bot is connected.")
        return

    import yfinance as yf

    df = yf.download(SYMBOL, period="5d", interval=f"{INTERVAL_MIN}m", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    if df.empty:
        print("No data")
        return
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")

    now = pd.Timestamp.now(tz="UTC")
    delta = pd.Timedelta(minutes=INTERVAL_MIN)
    df = df[df.index + delta <= now]  # keep only closed candles
    if df.empty:
        return

    last_close_time = df.index[-1] + delta
    if now - last_close_time > delta:
        print("Last candle is stale (market closed?)")
        return

    sig = detect(df)
    if not sig:
        print("No signal")
        return

    where = "low" if sig["side"] == "BUY" else "high"
    msg = (
        f"Gold 15m {sig['side']} signal\n"
        f"{sig['setup']} at swing {where} + confirmation candle\n"
        f"Entry (close): {sig['entry']:.2f}"
    )
    send(msg)
    print(msg)


if __name__ == "__main__":
    main()

