"""
StockTwits Sentiment Analysis Module.
Uses the StockTwits public API for real-time social sentiment.
"""

import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

import config
from utils.logger import setup_logger

logger = setup_logger("StockTwits")

BASE_URL = "https://api.stocktwits.com/api/2"


class StockTwitsSentiment:
    """Analyze sentiment from StockTwits."""

    def __init__(self):
        self.vader = SentimentIntensityAnalyzer()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OptionsTradingBot/1.0",
        })

    def get_sentiment(self, ticker: str) -> dict:
        """
        Get StockTwits sentiment for a ticker.

        Returns dict with score, mentions, bullish/bearish breakdown.
        """
        try:
            url = f"{BASE_URL}/streams/symbol/{ticker}.json"
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"StockTwits API error for {ticker}: {e}")
            return self._empty_result(ticker)

        messages = data.get("messages", [])
        if not messages:
            return self._empty_result(ticker)

        sentiments = []
        labeled_bullish = 0
        labeled_bearish = 0

        for msg in messages[: config.SENTIMENT["stocktwits_limit"]]:
            body = msg.get("body", "")

            # StockTwits has user-labeled sentiment
            label = (msg.get("entities", {}).get("sentiment", {})
                     .get("basic", None))

            if label == "Bullish":
                labeled_bullish += 1
                sentiments.append(0.5)  # Pre-labeled
            elif label == "Bearish":
                labeled_bearish += 1
                sentiments.append(-0.5)
            else:
                # Fall back to VADER analysis
                score = self.vader.polarity_scores(body)["compound"]
                sentiments.append(score)

        total = len(sentiments)
        avg_score = sum(sentiments) / total if total else 0

        bullish_count = sum(1 for s in sentiments if s > 0.1)
        bearish_count = sum(1 for s in sentiments if s < -0.1)
        neutral_count = total - bullish_count - bearish_count

        result = {
            "ticker": ticker,
            "score": round(avg_score, 4),
            "mentions": total,
            "bullish_pct": round(bullish_count / total * 100, 1) if total else 0,
            "bearish_pct": round(bearish_count / total * 100, 1) if total else 0,
            "neutral_pct": round(neutral_count / total * 100, 1) if total else 0,
            "labeled_bullish": labeled_bullish,
            "labeled_bearish": labeled_bearish,
            "source": "stocktwits",
        }

        logger.info(
            f"StockTwits sentiment for {ticker}: "
            f"score={result['score']}, mentions={result['mentions']}, "
            f"bull/bear labels={labeled_bullish}/{labeled_bearish}"
        )
        return result

    def get_trending(self) -> list[dict]:
        """Get StockTwits trending tickers."""
        try:
            url = f"{BASE_URL}/trending/symbols.json"
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            symbols = data.get("symbols", [])
            return [
                {
                    "ticker": s["symbol"],
                    "title": s.get("title", ""),
                    "watchlist_count": s.get("watchlist_count", 0),
                }
                for s in symbols[:20]
            ]
        except Exception as e:
            logger.warning(f"StockTwits trending error: {e}")
            return []

    def _empty_result(self, ticker: str) -> dict:
        return {
            "ticker": ticker,
            "score": 0.0,
            "mentions": 0,
            "bullish_pct": 0,
            "bearish_pct": 0,
            "neutral_pct": 0,
            "labeled_bullish": 0,
            "labeled_bearish": 0,
            "source": "stocktwits",
        }
