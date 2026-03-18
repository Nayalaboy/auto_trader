# Schwab AI Trading Bot — Setup Guide

## Project Structure

```
├── .env.example        # Copy to .env and fill in your credentials
├── auth.py             # OAuth2 flow + token management
├── market_data.py      # Quotes, price history, option chains
├── order_executor.py   # Order placement with risk guards + dry-run
├── bot.py              # Main loop: signals → risk checks → execution
├── requirements.txt
├── tokens/             # Auto-created — stores your OAuth token (gitignore this)
└── logs/               # Auto-created — daily trade log (JSONL)
```

---

## Quick Start

### 1. Install dependencies
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set up credentials
```bash
cp .env.example .env
# Fill in SCHWAB_APP_KEY, SCHWAB_APP_SECRET, TRADING_ACCOUNT_NUMBER
```

Get your key/secret from:
https://developer.schwab.com/dashboard/apps → View Details

### 3. Complete OAuth (first time only)
```bash
python auth.py
```
- A browser window opens. Log in with your **Schwab brokerage** credentials (not dev portal).
- You'll be redirected to a localhost URL. schwab-py captures it automatically.
- Token is saved to `tokens/schwab_token.json`. Do not share this file.

### 4. Run the bot in dry-run mode
```bash
python bot.py
```
`DRY_RUN=true` in your `.env` means orders are validated but never sent.
Check the output and `logs/trade_YYYYMMDD.jsonl` to verify signals.

### 5. Test individual modules
```bash
python market_data.py    # Fetch a quote + price history
python order_executor.py # Test a single dry-run order
```

---

## Safety Checklist Before Going Live

- [ ] Run dry-run for at least 5 trading days and review all signals
- [ ] Verify `TRADING_ACCOUNT_NUMBER` is correct
- [ ] Set `MAX_TRADE_VALUE_USD` to an amount you're comfortable losing entirely
- [ ] Implement real P&L tracking in `RiskGuard.check_daily_loss()`
- [ ] Wire in your actual sentiment scores in `get_sentiment_score()`
- [ ] Set `DRY_RUN=false` in `.env` only when confident

---

## Key Files to Customize

| File | What to add |
|------|-------------|
| `bot.py` → `get_sentiment_score()` | Your Reddit/Twitter/StockTwits sentiment pipeline |
| `bot.py` → `generate_signal()` | Tune RSI/MACD/BB thresholds or swap in ML model |
| `order_executor.py` → `RiskGuard.check_daily_loss()` | Wire in real P&L from trade log |
| `bot.py` → `WATCHLIST` | Your target symbols |

---

## Token Refresh
schwab-py handles token refresh automatically. The access token expires every 30 minutes,
but the library refreshes it transparently. The refresh token lasts 7 days — after that,
you'll need to re-run `python auth.py` to re-authenticate.

---

## Deployment (Cloud)
To run on a schedule without your machine:
1. Push this project to GitHub
2. Deploy on Google Cloud Run or a small Compute Engine VM
3. Use Cloud Scheduler to trigger `python bot.py` on market open (9:30 AM ET weekdays)
4. Store `.env` values as Secret Manager secrets, not as plain files
