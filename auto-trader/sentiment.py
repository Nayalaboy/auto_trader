"""
sentiment.py — Sentiment Aggregator
--------------------------------------
Pulls financial sentiment from 3 sources:
  1. StockTwits  — finance-specific social (free, no key needed)
  2. NewsAPI     — news headlines (free tier: 100 req/day)
  3. Reddit      — r/wallstreetbets, r/stocks, r/investing (free)

Returns a single sentiment score per symbol: -1.0 (bearish) to +1.0 (bullish)
"""

import os
import time
import logging
import requests
import yfinance as yf
from newsapi import NewsApiClient
from textblob import TextBlob
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# ── Clients ──────────────────────────────────────────────────────────────────

def _get_newsapi_client():
    return NewsApiClient(api_key=os.getenv("NEWSAPI_KEY"))

# ── Reddit is optional — only loads if credentials are present ───────────────
def _get_reddit_client():
    client_id     = os.getenv("REDDIT_CLIENT_ID", "")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
    if not client_id or client_id == "your_reddit_client_id":
        return None
    import praw
    return praw.Reddit(
        client_id     = client_id,
        client_secret = client_secret,
        user_agent    = os.getenv("REDDIT_USER_AGENT", "OptionsTradingBot/1.0"),
    )


# ── Sentiment Scorer ─────────────────────────────────────────────────────────

def _score_text(text: str) -> float:
    """
    Uses TextBlob polarity as base score (-1.0 to +1.0).
    Boosts score for finance-specific bullish/bearish keywords.
    """
    if not text:
        return 0.0

    polarity = TextBlob(text).sentiment.polarity

    # Finance keyword boosters
    bullish_keywords = [
        "buy", "bull", "bullish", "long", "calls", "breakout",
        "upside", "beat", "strong", "upgrade", "surge", "rally",
        "moon", "rocket", "squeeze", "oversold",
    ]
    bearish_keywords = [
        "sell", "bear", "bearish", "short", "puts", "breakdown",
        "downside", "miss", "weak", "downgrade", "crash", "dump",
        "drop", "overbought", "recession", "layoffs",
    ]

    text_lower = text.lower()
    boost = 0.0
    for word in bullish_keywords:
        if word in text_lower:
            boost += 0.05
    for word in bearish_keywords:
        if word in text_lower:
            boost -= 0.05

    return max(-1.0, min(1.0, polarity + boost))


# ── Source 1: Yahoo Finance News ─────────────────────────────────────────────

def score_yahoo(symbol: str) -> tuple[float, int]:
    """
    Returns (sentiment_score, article_count).
    Uses yfinance to pull ticker-specific news headlines — no API key needed.
    """
    try:
        ticker   = yf.Ticker(symbol)
        news     = ticker.news
        if not news:
            return 0.0, 0

        scores = []
        for item in news:
            content = item.get("content", {})
            title   = content.get("title", "")
            summary = content.get("summary", "")
            text    = f"{title} {summary}"
            if text.strip():
                scores.append(_score_text(text))

        if not scores:
            return 0.0, 0

        avg = sum(scores) / len(scores)
        return round(avg, 4), len(scores)

    except Exception as e:
        log.warning(f"Yahoo Finance fetch failed for {symbol}: {e}")
        return 0.0, 0


# ── Source 2: NewsAPI ─────────────────────────────────────────────────────────

def score_newsapi(symbol: str, hours_back: int = 24) -> tuple[float, int]:
    """
    Returns (sentiment_score, article_count).
    Scores headlines + descriptions for the symbol.
    """
    try:
        client   = _get_newsapi_client()
        response = client.get_everything(
            q            = f"{symbol} stock",
            language     = "en",
            sort_by      = "publishedAt",
            page_size    = 20,
        )
        articles = response.get("articles", [])
        if not articles:
            return 0.0, 0

        scores = []
        for article in articles:
            text  = f"{article.get('title', '')} {article.get('description', '')}"
            scores.append(_score_text(text))

        avg = sum(scores) / len(scores)
        return round(avg, 4), len(scores)

    except Exception as e:
        log.warning(f"NewsAPI fetch failed for {symbol}: {e}")
        return 0.0, 0


# ── Source 3: Reddit ──────────────────────────────────────────────────────────

SUBREDDITS = ["wallstreetbets", "stocks", "investing", "options"]

def score_reddit(symbol: str, post_limit: int = 20) -> tuple[float, int]:
    """
    Returns (sentiment_score, post_count).
    Skipped automatically if Reddit credentials are not configured.
    """
    reddit = _get_reddit_client()
    if reddit is None:
        log.debug("Reddit credentials not configured — skipping.")
        return 0.0, 0

    try:
        scores = []
        for sub in SUBREDDITS:
            subreddit = reddit.subreddit(sub)
            for post in subreddit.search(symbol, sort="new", limit=post_limit // len(SUBREDDITS)):
                text = f"{post.title} {post.selftext[:200]}"
                scores.append(_score_text(text))
            time.sleep(0.5)

        if not scores:
            return 0.0, 0

        avg = sum(scores) / len(scores)
        return round(avg, 4), len(scores)

    except Exception as e:
        log.warning(f"Reddit fetch failed for {symbol}: {e}")
        return 0.0, 0


# ── Aggregator ────────────────────────────────────────────────────────────────

# Source weights
WEIGHTS = {
    "yahoo":   0.60,   # Ticker-specific news — most relevant
    "newsapi": 0.40,   # Broader market news
    "reddit":  0.00,   # Optional — add Reddit credentials to enable
}

def get_sentiment_score(symbol: str, verbose: bool = False) -> float:
    """
    Main entry point. Returns a single weighted sentiment score.
    Score range: -1.0 (very bearish) to +1.0 (very bullish)
    """
    yh_score,   yh_count   = score_yahoo(symbol)
    news_score, news_count = score_newsapi(symbol)
    rd_score,   rd_count   = score_reddit(symbol)

    total_weight = 0.0
    weighted_sum = 0.0

    if yh_count > 0:
        weighted_sum += yh_score * WEIGHTS["yahoo"]
        total_weight += WEIGHTS["yahoo"]

    if news_count > 0:
        weighted_sum += news_score * WEIGHTS["newsapi"]
        total_weight += WEIGHTS["newsapi"]

    if rd_count > 0:
        weighted_sum += rd_score * WEIGHTS["reddit"]
        total_weight += WEIGHTS["reddit"]

    final_score = round(weighted_sum / total_weight, 4) if total_weight > 0 else 0.0

    if verbose:
        print(f"\n📊 Sentiment for {symbol}")
        print(f"   Yahoo Finance : {yh_score:+.4f}  ({yh_count} articles)")
        print(f"   NewsAPI       : {news_score:+.4f}  ({news_count} articles)")
        print(f"   Reddit        : {rd_score:+.4f}  ({rd_count} posts)")
        print(f"   ─────────────────────────────────")
        print(f"   FINAL         : {final_score:+.4f}")
        if final_score > 0.2:
            print(f"   Signal        : 🟢 BULLISH")
        elif final_score < -0.2:
            print(f"   Signal        : 🔴 BEARISH")
        else:
            print(f"   Signal        : ⚪ NEUTRAL")

    return final_score


# ── Quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["SPY", "AAPL"]

    print("🔍 Running sentiment analysis...\n")
    for symbol in symbols:
        get_sentiment_score(symbol, verbose=True)
        time.sleep(1)