"""
News Sentiment Analysis Module.
Aggregates and scores news from NewsAPI and financial RSS feeds.
"""

from datetime import datetime, timedelta

import feedparser
import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from utils.logger import setup_logger

logger = setup_logger("News")

# Financial RSS feeds (free, no API key needed)
RSS_FEEDS = {
    "yahoo_finance": "https://finance.yahoo.com/news/rssindex",
    "marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories/",
    "cnbc": "https://search.cnbc.com/rs/search/combinedcms/view.xml"
            "?partnerId=wrss01&id=100003114",
    "reuters_business": "https://feeds.reuters.com/reuters/businessNews",
    "seeking_alpha": "https://seekingalpha.com/market_currents.xml",
}


class NewsSentiment:
    """Analyze sentiment from news sources."""

    def __init__(self, newsapi_key: str = None):
        self.newsapi_key = newsapi_key
        self.vader = SentimentIntensityAnalyzer()
        self.session = requests.Session()

    def _search_newsapi(self, query: str, hours_back: int = 24) -> list[dict]:
        """Search NewsAPI for articles."""
        if not self.newsapi_key:
            return []

        try:
            from_date = (
                datetime.utcnow() - timedelta(hours=hours_back)
            ).strftime("%Y-%m-%dT%H:%M:%S")

            url = "https://newsapi.org/v2/everything"
            params = {
                "q": query,
                "from": from_date,
                "sortBy": "relevancy",
                "language": "en",
                "pageSize": 20,
                "apiKey": self.newsapi_key,
            }
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            articles = []
            for article in data.get("articles", []):
                text = f"{article.get('title', '')} {article.get('description', '')}"
                score = self.vader.polarity_scores(text)["compound"]
                articles.append({
                    "title": article.get("title", ""),
                    "source": article.get("source", {}).get("name", "Unknown"),
                    "url": article.get("url", ""),
                    "published": article.get("publishedAt", ""),
                    "sentiment": score,
                })
            return articles

        except Exception as e:
            logger.warning(f"NewsAPI error for '{query}': {e}")
            return []

    def _search_rss(self, ticker: str) -> list[dict]:
        """Search RSS feeds for mentions of a ticker."""
        articles = []

        for feed_name, feed_url in RSS_FEEDS.items():
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:20]:
                    title = entry.get("title", "")
                    summary = entry.get("summary", "")
                    text = f"{title} {summary}"

                    # Check if ticker is mentioned
                    if ticker.upper() not in text.upper():
                        # Also try company name matching (basic)
                        continue

                    score = self.vader.polarity_scores(text)["compound"]
                    articles.append({
                        "title": title[:200],
                        "source": feed_name,
                        "url": entry.get("link", ""),
                        "published": entry.get("published", ""),
                        "sentiment": score,
                    })
            except Exception as e:
                logger.debug(f"RSS feed error ({feed_name}): {e}")

        return articles

    def get_sentiment(self, ticker: str, hours_back: int = 24) -> dict:
        """
        Get news sentiment for a ticker.

        Combines NewsAPI + RSS feeds.
        """
        all_articles = []

        # NewsAPI search
        newsapi_articles = self._search_newsapi(
            f"{ticker} stock", hours_back=hours_back
        )
        all_articles.extend(newsapi_articles)

        # RSS feed search
        rss_articles = self._search_rss(ticker)
        all_articles.extend(rss_articles)

        if not all_articles:
            return {
                "ticker": ticker,
                "score": 0.0,
                "mentions": 0,
                "bullish_pct": 0,
                "bearish_pct": 0,
                "neutral_pct": 0,
                "articles": [],
                "source": "news",
            }

        sentiments = [a["sentiment"] for a in all_articles]
        avg_score = sum(sentiments) / len(sentiments)

        bullish = sum(1 for s in sentiments if s > 0.1)
        bearish = sum(1 for s in sentiments if s < -0.1)
        neutral = len(sentiments) - bullish - bearish
        total = len(sentiments)

        # Sort by sentiment strength for top articles
        top_articles = sorted(
            all_articles, key=lambda x: abs(x["sentiment"]), reverse=True
        )[:5]

        result = {
            "ticker": ticker,
            "score": round(avg_score, 4),
            "mentions": total,
            "bullish_pct": round(bullish / total * 100, 1),
            "bearish_pct": round(bearish / total * 100, 1),
            "neutral_pct": round(neutral / total * 100, 1),
            "articles": top_articles,
            "source": "news",
        }

        logger.info(
            f"News sentiment for {ticker}: "
            f"score={result['score']}, articles={result['mentions']}"
        )
        return result

    def get_market_sentiment(self, hours_back: int = 12) -> dict:
        """Get overall market sentiment from news."""
        queries = ["stock market", "S&P 500", "Wall Street", "Federal Reserve"]
        all_articles = []

        for query in queries:
            articles = self._search_newsapi(query, hours_back=hours_back)
            all_articles.extend(articles)

        if not all_articles:
            return {"score": 0.0, "articles": 0, "source": "news_market"}

        avg = sum(a["sentiment"] for a in all_articles) / len(all_articles)
        return {
            "score": round(avg, 4),
            "articles": len(all_articles),
            "source": "news_market",
        }
