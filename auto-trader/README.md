# 🤖 Automated Options Trading Bot with Sentiment Analysis

## ⚠️ DISCLAIMER
**This is NOT financial advice. This tool is for educational and experimental purposes only.**
- Options trading involves significant risk of loss
- Past performance does not guarantee future results
- Always paper trade first before using real money
- The developers are not responsible for any financial losses

## Overview

This system combines:
- **Schwab Trader API** (formerly TD Ameritrade) for options trading execution
- **Reddit sentiment analysis** (r/wallstreetbets, r/options, r/stocks)
- **StockTwits sentiment** via their API
- **News sentiment** via NewsAPI and financial RSS feeds
- **Technical indicators** (RSI, MACD, Bollinger Bands, IV Rank)
- **AI-powered signal generation** combining all data sources

## Architecture

```
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│  Reddit API     │   │  StockTwits API  │   │  NewsAPI        │
│  (PRAW)         │   │                  │   │  + RSS Feeds    │
└────────┬────────┘   └────────┬─────────┘   └────────┬────────┘
         │                     │                      │
         ▼                     ▼                      ▼
┌──────────────────────────────────────────────────────────────┐
│                  Sentiment Aggregator                        │
│  • NLP scoring (VADER + FinBERT)                             │
│  • Volume-weighted sentiment                                 │
│  • Trend detection                                           │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                  Signal Generator                            │
│  • Combines sentiment + technicals                           │
│  • Risk scoring                                              │
│  • Options strategy selector                                 │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│              Schwab Trader API Executor                       │
│  • Paper trading mode (default)                              │
│  • Position sizing & risk management                         │
│  • Order execution & monitoring                              │
└──────────────────────────────────────────────────────────────┘
```

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Get API Keys

#### Schwab Trader API
1. Go to https://developer.schwab.com
2. Register for an individual developer account
3. Create an app and get your App Key and Secret
4. Set callback URL to `https://127.0.0.1:8080/callback`

#### Reddit API
1. Go to https://www.reddit.com/prefs/apps
2. Create a "script" application
3. Note down client_id and client_secret

#### StockTwits
1. Go to https://api.stocktwits.com/developers
2. Register an app (or use public endpoints)

#### NewsAPI
1. Go to https://newsapi.org
2. Get a free API key

### 3. Configure Environment
```bash
cp .env.example .env
# Edit .env with your API keys
```

### 4. Run
```bash
# Paper trading mode (recommended to start)
python main.py --mode paper

# Live trading (use with extreme caution!)
python main.py --mode live

# Analysis only (no trades)
python main.py --mode analyze
```

## Configuration

Edit `config.py` to customize:
- Watchlist of tickers
- Risk parameters (max position size, max loss, etc.)
- Sentiment thresholds
- Technical indicator parameters
- Options strategy preferences

## File Structure
```
├── main.py                  # Entry point & orchestrator
├── config.py                # All configuration
├── requirements.txt         # Dependencies
├── .env.example             # Environment variable template
├── sentiment/
│   ├── reddit_sentiment.py  # Reddit scraping & analysis
│   ├── stocktwits.py        # StockTwits sentiment
│   ├── news_sentiment.py    # News & RSS sentiment
│   └── aggregator.py        # Combines all sentiment sources
├── technicals/
│   └── indicators.py        # Technical analysis
├── trading/
│   ├── schwab_client.py     # Schwab API wrapper
│   ├── options_strategy.py  # Options strategy selection
│   ├── risk_manager.py      # Risk management
│   └── executor.py          # Order execution
├── signals/
│   └── signal_generator.py  # Signal generation engine
└── utils/
    └── logger.py            # Logging utilities
```
