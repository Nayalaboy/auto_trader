"""
Configuration for the Options Trading Bot.
Adjust these parameters to fit your risk tolerance and strategy.
"""

# ============================================================
# WATCHLIST - Tickers to monitor
# ============================================================
WATCHLIST = [
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN",
    "META", "GOOGL", "AMD", "PLTR", "SOFI", "COIN", "MARA",
]

# ============================================================
# RISK MANAGEMENT
# ============================================================
RISK = {
    "max_portfolio_risk_pct": 5.0,       # Max % of portfolio at risk at any time
    "max_single_trade_risk_pct": 1.0,    # Max % of portfolio per trade
    "max_open_positions": 5,             # Max simultaneous positions
    "max_daily_loss_pct": 3.0,           # Stop trading if daily loss exceeds this
    "min_account_balance": 5000,         # Don't trade below this balance
    "default_stop_loss_pct": 50.0,       # Close option if it loses 50% of value
    "default_take_profit_pct": 100.0,    # Close option if it gains 100%
    "min_days_to_expiry": 7,             # Minimum DTE for options
    "max_days_to_expiry": 45,            # Maximum DTE for options
}

# ============================================================
# SENTIMENT THRESHOLDS
# ============================================================
SENTIMENT = {
    # Score range: -1.0 (very bearish) to +1.0 (very bullish)
    "strong_bullish": 0.6,
    "bullish": 0.3,
    "neutral_low": -0.15,
    "neutral_high": 0.15,
    "bearish": -0.3,
    "strong_bearish": -0.6,

    # Minimum mentions to consider sentiment valid
    "min_mentions": 5,

    # Source weights (must sum to 1.0)
    "weights": {
        "reddit": 0.30,
        "stocktwits": 0.25,
        "news": 0.30,
        "technical": 0.15,
    },

    # Reddit subreddits to monitor
    "reddit_subreddits": [
        "wallstreetbets",
        "options",
        "stocks",
        "investing",
        "thetagang",
    ],

    # Reddit post limit per subreddit
    "reddit_post_limit": 100,

    # StockTwits message limit
    "stocktwits_limit": 50,
}

# ============================================================
# TECHNICAL INDICATORS
# ============================================================
TECHNICALS = {
    "rsi_period": 14,
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "bb_period": 20,
    "bb_std": 2.0,
    "sma_short": 20,
    "sma_long": 50,
    "volume_avg_period": 20,
}

# ============================================================
# OPTIONS STRATEGY PREFERENCES
# ============================================================
STRATEGIES = {
    # Which strategies to consider
    "enabled": [
        "long_call",        # Bullish
        "long_put",         # Bearish
        "bull_call_spread",  # Moderately bullish
        "bear_put_spread",   # Moderately bearish
        "iron_condor",       # Neutral / range-bound
        "covered_call",      # Slightly bullish (if shares owned)
        "cash_secured_put",  # Slightly bullish
    ],

    # Preferred delta ranges for option selection
    "long_option_delta": (0.30, 0.50),   # ATM-ish for directional
    "spread_width": 5,                    # Dollar width of spreads
    "iron_condor_delta": (0.15, 0.20),   # Wings for iron condors

    # Minimum open interest and volume
    "min_open_interest": 100,
    "min_volume": 50,

    # IV rank thresholds
    "high_iv_rank": 50,    # Above this = prefer selling strategies
    "low_iv_rank": 30,     # Below this = prefer buying strategies
}

# ============================================================
# SIGNAL GENERATION
# ============================================================
SIGNALS = {
    # Minimum combined score to generate a trade signal
    "min_signal_score": 0.55,

    # How often to run the analysis (in minutes)
    "scan_interval_minutes": 15,

    # Market hours (Eastern Time)
    "market_open": "09:30",
    "market_close": "16:00",

    # Don't enter trades in last N minutes before close
    "no_entry_before_close_minutes": 30,
}

# ============================================================
# LOGGING
# ============================================================
LOGGING = {
    "level": "INFO",
    "file": "trading_bot.log",
    "max_size_mb": 50,
    "backup_count": 5,
}
