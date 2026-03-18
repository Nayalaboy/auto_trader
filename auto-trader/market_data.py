"""
market_data.py — Market Data Fetcher
-------------------------------------
Pulls quotes, price history, and option chains from Schwab API.
All data methods return clean dicts/DataFrames ready for signal logic.
"""

import pandas as pd
from datetime import datetime, timedelta
from schwab.client import Client
import schwab


def get_quote(client: Client, symbol: str) -> dict:
    """
    Fetch real-time quote for a single ticker.
    Returns a flat dict with the most useful fields.
    """
    resp = client.get_quote(symbol)
    resp.raise_for_status()
    data = resp.json().get(symbol, {})

    quote = data.get("quote", {})
    return {
        "symbol":       symbol,
        "last":         quote.get("lastPrice"),
        "bid":          quote.get("bidPrice"),
        "ask":          quote.get("askPrice"),
        "volume":       quote.get("totalVolume"),
        "change_pct":   quote.get("netPercentChange"),
        "52w_high":     quote.get("52WeekHigh"),
        "52w_low":      quote.get("52WeekLow"),
        "timestamp":    datetime.now().isoformat(),
    }


def get_price_history(
    client: Client,
    symbol: str,
    days: int = 60,
    frequency: str = "daily",
) -> pd.DataFrame:
    """
    Fetch OHLCV price history as a DataFrame.

    Args:
        days:      How many calendar days back to fetch
        frequency: 'minute', 'daily', 'weekly', 'monthly'
    """
    freq_map = {
        "minute":  (Client.PriceHistory.Frequency.EVERY_MINUTE,
                    Client.PriceHistory.FrequencyType.MINUTE),
        "daily":   (Client.PriceHistory.Frequency.DAILY,
                    Client.PriceHistory.FrequencyType.DAILY),
        "weekly":  (Client.PriceHistory.Frequency.WEEKLY,
                    Client.PriceHistory.FrequencyType.WEEKLY),
        "monthly": (Client.PriceHistory.Frequency.MONTHLY,
                    Client.PriceHistory.FrequencyType.MONTHLY),
    }

    freq, freq_type = freq_map[frequency]
    end_dt   = datetime.now()
    start_dt = end_dt - timedelta(days=days)

    resp = client.get_price_history(
        symbol=symbol,
        period_type=Client.PriceHistory.PeriodType.YEAR,
        frequency_type=freq_type,
        frequency=freq,
        start_datetime=start_dt,
        end_datetime=end_dt,
    )
    resp.raise_for_status()

    candles = resp.json().get("candles", [])
    df = pd.DataFrame(candles)

    if not df.empty:
        df["datetime"] = pd.to_datetime(df["datetime"], unit="ms")
        df = df.rename(columns={"datetime": "date"})
        df = df.set_index("date").sort_index()

    return df[["open", "high", "low", "close", "volume"]]


def get_option_chain(client: Client, symbol: str, expiry_days: int = 30) -> dict:
    """
    Fetch option chain for a symbol within a target expiry window.
    Returns raw JSON from Schwab (calls + puts nested by strike/expiry).
    """
    today    = datetime.now()
    from_dt  = today
    to_dt    = today + timedelta(days=expiry_days)

    resp = client.get_option_chain(
        symbol=symbol,
        contract_type=Client.Options.ContractType.ALL,
        from_date=from_dt,
        to_date=to_dt,
        option_type=Client.Options.Type.STANDARD,
    )
    resp.raise_for_status()
    return resp.json()


# ── Quick test ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from auth import get_client

    client = get_client()
    symbol = "SPY"

    print(f"\n📈 Quote for {symbol}:")
    quote = get_quote(client, symbol)
    for k, v in quote.items():
        print(f"   {k}: {v}")

    print(f"\n📊 Price history ({symbol}, last 30 days, daily):")
    df = get_price_history(client, symbol, days=30)
    print(df.tail(5).to_string())
