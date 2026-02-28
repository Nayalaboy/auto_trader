"""
Reddit Sentiment Analysis Module.
Scrapes and analyzes posts/comments from financial subreddits.
"""

import re
from datetime import datetime, timedelta
from typing import Optional

import praw
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

import config
from utils.logger import setup_logger

logger = setup_logger("Reddit")


class RedditSentiment:
    """Analyze sentiment from Reddit financial subreddits."""

    def __init__(self, client_id: str, client_secret: str, user_agent: str):
        self.reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        self.vader = SentimentIntensityAnalyzer()

        # Add financial-specific lexicon updates to VADER
        financial_lexicon = {
            "bullish": 2.5, "bearish": -2.5, "moon": 2.0, "mooning": 2.5,
            "rocket": 1.5, "tendies": 1.5, "diamond hands": 2.0,
            "paper hands": -1.0, "yolo": 1.0, "squeeze": 1.5,
            "short squeeze": 2.0, "calls": 0.5, "puts": -0.5,
            "pump": 1.0, "dump": -2.0, "crash": -2.5, "dip": -0.5,
            "buy the dip": 1.5, "bag holder": -2.0, "rug pull": -3.0,
            "to the moon": 3.0, "drill": -2.0, "drilling": -2.0,
            "rip": -1.5, "tank": -2.0, "tanking": -2.5,
            "rally": 2.0, "breakout": 2.0, "support": 1.0,
            "resistance": -0.5, "oversold": 1.0, "overbought": -1.0,
            "undervalued": 1.5, "overvalued": -1.5, "long": 1.0,
            "short": -1.0, "calls printing": 2.5, "puts printing": -2.5,
            "green": 1.0, "red": -1.0, "blood": -2.0, "bloody": -2.0,
        }
        self.vader.lexicon.update(financial_lexicon)

    def _extract_tickers(self, text: str) -> list[str]:
        """Extract stock tickers from text (e.g., $AAPL or AAPL)."""
        # Match $TICKER or standalone uppercase 2-5 letter words
        pattern = r'\$([A-Z]{1,5})\b|(?<!\w)([A-Z]{2,5})(?!\w)'
        matches = re.findall(pattern, text)
        tickers = set()
        for m in matches:
            ticker = m[0] or m[1]
            # Filter out common words that look like tickers
            common_words = {
                "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL",
                "CAN", "HER", "WAS", "ONE", "OUR", "OUT", "HAS", "HIS",
                "HOW", "ITS", "LET", "MAY", "NEW", "NOW", "OLD", "SEE",
                "WAY", "WHO", "DID", "GOT", "HAS", "HIM", "HIT", "HOW",
                "MAN", "OIL", "SAY", "SHE", "TOO", "USE", "CEO", "CFO",
                "IPO", "ATH", "ATL", "IMO", "EDIT", "LMAO", "JUST",
                "LIKE", "BEEN", "THIS", "THAT", "WITH", "HAVE", "FROM",
                "THEY", "WILL", "WHAT", "WHEN", "MAKE", "THAN", "THEM",
                "WANT", "VERY", "MUCH", "SOME", "INTO", "OVER", "SUCH",
                "TAKE", "YEAR", "ALSO", "BACK", "HOLD", "LONG", "VERY",
                "POST", "FREE", "GOOD", "BEST", "PUMP", "DUMP", "YOLO",
                "FOMO", "HODL", "REKT", "MOON", "GAIN", "LOSS",
            }
            if ticker in config.WATCHLIST or (
                ticker not in common_words and len(ticker) >= 2
            ):
                tickers.add(ticker)
        return list(tickers)

    def _analyze_text(self, text: str) -> float:
        """Get sentiment score for a piece of text using VADER."""
        scores = self.vader.polarity_scores(text)
        return scores["compound"]  # Range: -1 to +1

    def get_sentiment(
        self, ticker: Optional[str] = None, hours_back: int = 24
    ) -> dict:
        """
        Get Reddit sentiment for a ticker or overall market.

        Returns:
            {
                "ticker": str,
                "score": float (-1 to 1),
                "mentions": int,
                "bullish_pct": float,
                "bearish_pct": float,
                "neutral_pct": float,
                "top_posts": list[dict],
                "source": "reddit"
            }
        """
        all_sentiments = []
        top_posts = []
        cutoff = datetime.utcnow() - timedelta(hours=hours_back)

        for sub_name in config.SENTIMENT["reddit_subreddits"]:
            try:
                subreddit = self.reddit.subreddit(sub_name)
                posts = subreddit.hot(
                    limit=config.SENTIMENT["reddit_post_limit"]
                )

                for post in posts:
                    created = datetime.utcfromtimestamp(post.created_utc)
                    if created < cutoff:
                        continue

                    text = f"{post.title} {post.selftext}"

                    # If filtering by ticker, check if mentioned
                    if ticker:
                        mentioned_tickers = self._extract_tickers(text)
                        if ticker not in mentioned_tickers:
                            continue

                    score = self._analyze_text(text)
                    weight = min(post.score / 100, 5.0) + 1  # Upvote weighting
                    all_sentiments.append((score, weight))

                    if len(top_posts) < 10:
                        top_posts.append({
                            "title": post.title[:100],
                            "score": post.score,
                            "sentiment": score,
                            "subreddit": sub_name,
                            "url": f"https://reddit.com{post.permalink}",
                        })

                    # Also analyze top comments
                    post.comments.replace_more(limit=0)
                    for comment in post.comments[:10]:
                        comment_text = comment.body
                        if ticker:
                            if ticker not in self._extract_tickers(comment_text):
                                continue
                        c_score = self._analyze_text(comment_text)
                        c_weight = min(comment.score / 50, 3.0) + 1
                        all_sentiments.append((c_score, c_weight))

            except Exception as e:
                logger.warning(f"Error scraping r/{sub_name}: {e}")
                continue

        if not all_sentiments:
            return {
                "ticker": ticker or "MARKET",
                "score": 0.0,
                "mentions": 0,
                "bullish_pct": 0,
                "bearish_pct": 0,
                "neutral_pct": 0,
                "top_posts": [],
                "source": "reddit",
            }

        # Calculate weighted average sentiment
        total_weight = sum(w for _, w in all_sentiments)
        weighted_score = sum(s * w for s, w in all_sentiments) / total_weight

        # Calculate sentiment distribution
        bullish = sum(1 for s, _ in all_sentiments if s > 0.1)
        bearish = sum(1 for s, _ in all_sentiments if s < -0.1)
        neutral = len(all_sentiments) - bullish - bearish
        total = len(all_sentiments)

        result = {
            "ticker": ticker or "MARKET",
            "score": round(weighted_score, 4),
            "mentions": total,
            "bullish_pct": round(bullish / total * 100, 1),
            "bearish_pct": round(bearish / total * 100, 1),
            "neutral_pct": round(neutral / total * 100, 1),
            "top_posts": sorted(top_posts, key=lambda x: x["score"], reverse=True),
            "source": "reddit",
        }

        logger.info(
            f"Reddit sentiment for {result['ticker']}: "
            f"score={result['score']}, mentions={result['mentions']}"
        )
        return result

    def get_trending_tickers(self, hours_back: int = 12) -> list[dict]:
        """Find the most mentioned tickers across subreddits."""
        ticker_counts = {}
        ticker_sentiments = {}

        for sub_name in config.SENTIMENT["reddit_subreddits"]:
            try:
                subreddit = self.reddit.subreddit(sub_name)
                cutoff = datetime.utcnow() - timedelta(hours=hours_back)

                for post in subreddit.hot(limit=50):
                    created = datetime.utcfromtimestamp(post.created_utc)
                    if created < cutoff:
                        continue

                    text = f"{post.title} {post.selftext}"
                    tickers = self._extract_tickers(text)
                    score = self._analyze_text(text)

                    for t in tickers:
                        ticker_counts[t] = ticker_counts.get(t, 0) + 1
                        if t not in ticker_sentiments:
                            ticker_sentiments[t] = []
                        ticker_sentiments[t].append(score)

            except Exception as e:
                logger.warning(f"Error in trending scan r/{sub_name}: {e}")

        trending = []
        for ticker, count in sorted(
            ticker_counts.items(), key=lambda x: x[1], reverse=True
        )[:20]:
            avg_sentiment = sum(ticker_sentiments[ticker]) / len(
                ticker_sentiments[ticker]
            )
            trending.append({
                "ticker": ticker,
                "mentions": count,
                "avg_sentiment": round(avg_sentiment, 4),
            })

        return trending
