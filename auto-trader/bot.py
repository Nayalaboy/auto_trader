"""
bot.py — Main Trading Bot Runner
----------------------------------
Orchestrates the full loop:
  1. Fetch market data
  2. Compute signals (RSI + sentiment stub)
  3. Run risk checks
  4. Execute or dry-run orders
  5. Log results

Run manually or via scheduler (cron / Cloud Scheduler).
"""
import os
import time
import logging
from datetime import datetime
from sentiment import get_sentiment_score


import pandas as pd
from dotenv import load_dotenv

from auth import get_client
from market_data import get_quote, get_price_history
from order_executor import OrderExecutor, TradeSignal, Side

load_dotenv()

log = logging.getLogger(__name__)

# ── Watchlist ────────────────────────────────────────────────────────────────
WATCHLIST = ["SPY", "QQQ", "AAPL", "MSFT"]


# ── Technical Indicators ─────────────────────────────────────────────────────

def compute_rsi(series: pd.Series, period: int = 14) -> float:
    """Standard RSI calculation. Returns latest RSI value."""
    delta  = series.diff()
    gain   = delta.clip(lower=0).rolling(period).mean()
    loss   = (-delta.clip(upper=0)).rolling(period).mean()
    rs     = gain / loss
    rsi    = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 2)


def compute_macd(series: pd.Series) -> dict:
    """Returns MACD line, signal line, and histogram (latest values)."""
    ema12    = series.ewm(span=12, adjust=False).mean()
    ema26    = series.ewm(span=26, adjust=False).mean()
    macd     = ema12 - ema26
    signal   = macd.ewm(span=9, adjust=False).mean()
    hist     = macd - signal
    return {
        "macd":   round(macd.iloc[-1], 4),
        "signal": round(signal.iloc[-1], 4),
        "hist":   round(hist.iloc[-1], 4),
    }


def compute_bollinger(series: pd.Series, period: int = 20) -> dict:
    """Returns upper/mid/lower Bollinger Bands and %B for latest bar."""
    mid   = series.rolling(period).mean()
    std   = series.rolling(period).std()
    upper = mid + 2 * std
    lower = mid - 2 * std
    pct_b = (series - lower) / (upper - lower)
    return {
        "upper": round(upper.iloc[-1], 2),
        "mid":   round(mid.iloc[-1], 2),
        "lower": round(lower.iloc[-1], 2),
        "pct_b": round(pct_b.iloc[-1], 4),
    }





# ── Signal Logic ─────────────────────────────────────────────────────────────

def generate_signal(symbol: str, df: pd.DataFrame, sentiment: float) -> dict | None:
    """
    Combines RSI + MACD + Bollinger + sentiment into a simple signal.

    Returns a dict with side/confidence/reason, or None if no signal.

    Entry rules (long only for now):
      BUY  if RSI < 35 AND sentiment > 0.2 AND MACD hist > 0
      SELL if RSI > 70 OR (pct_b > 0.95 AND sentiment < -0.2)
    """
    close     = df["close"]
    rsi       = compute_rsi(close)
    macd      = compute_macd(close)
    boll      = compute_bollinger(close)

    log.info(
        f"{symbol} | RSI={rsi} | MACD_hist={macd['hist']} | "
        f"BB%B={boll['pct_b']} | Sentiment={sentiment}"
    )

    # BUY signal
    if rsi < 38 and sentiment > 0.1:
        # MACD confirmation preferred but not required
        macd_bonus = 0.1 if macd["hist"] > 0 else 0.0
        confidence = round(((38 - rsi) / 38 * 0.5) + (sentiment * 0.4) + macd_bonus, 3)
        if confidence > 0.15:  # minimum confidence threshold
            return {
                "side":       Side.BUY,
                "reason":     f"RSI={rsi} + sentiment={sentiment} + MACD={macd['hist']:.3f}",
                "confidence": confidence,
            }
        

    # SELL signal
    if rsi > 70 or (boll["pct_b"] > 0.95 and sentiment < -0.2):
        confidence = round(((rsi - 70) / 30 * 0.5) + (abs(sentiment) * 0.5), 3)
        return {
            "side":       Side.SELL,
            "reason":     f"RSI overbought ({rsi}) or BB upper breach + bearish sentiment",
            "confidence": confidence,
        }

    return None


# ── Position Sizing ──────────────────────────────────────────────────────────

def compute_quantity(price: float, max_usd: float = 500.0) -> int:
    """Simple fixed-dollar position sizing."""
    return max(1, int(max_usd // price))


# ── Main Loop ────────────────────────────────────────────────────────────────

def run():
    print(f"\n{'='*55}")
    print(f"  Schwab Trading Bot — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Mode: {'DRY RUN ✓' if os.getenv('DRY_RUN','true').lower()=='true' else '🚨 LIVE'}")
    print(f"{'='*55}\n")

    client   = get_client()
    executor = OrderExecutor(client)

    for symbol in WATCHLIST:
        print(f"--- Analyzing {symbol} ---")

        try:
            df        = get_price_history(client, symbol, days=60)
            quote     = get_quote(client, symbol)
            price     = quote.get("last") or 0
            sentiment = get_sentiment_score(symbol)
            sig_data  = generate_signal(symbol, df, sentiment)

            if sig_data is None:
                print(f"   No signal for {symbol}. Skipping.\n")
                continue

            quantity = compute_quantity(price)
            signal   = TradeSignal(
                symbol     = symbol,
                side       = sig_data["side"],
                quantity   = quantity,
                reason     = sig_data["reason"],
                confidence = sig_data["confidence"],
                strategy   = "rsi_macd_bb_sentiment_v1",
            )

            result = executor.execute(signal)
            print(f"   ➜ {result.status}: {result.message}\n")

        except Exception as e:
            log.error(f"Error processing {symbol}: {e}", exc_info=True)

        time.sleep(0.5)  # Respect API rate limits between tickers

    print("✅ Bot run complete.\n")


if __name__ == "__main__":
    run()
