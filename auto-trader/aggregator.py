"""
Sentiment Aggregator.
Combines sentiment from Reddit, StockTwits, and News into a single score.
"""

from typing import Optional

import config
from utils.logger import setup_logger

logger = setup_logger("Aggregator")


class SentimentAggregator:
    """Combine multiple sentiment sources into a unified score."""

    def __init__(self, reddit=None, stocktwits=None, news=None):
        self.reddit = reddit
        self.stocktwits = stocktwits
        self.news = news

    def get_combined_sentiment(self, ticker: str) -> dict:
        """
        Get aggregated sentiment from all sources.

        Returns:
            {
                "ticker": str,
                "combined_score": float,  # -1 to +1
                "signal": str,            # "strong_bullish", "bullish", etc.
                "confidence": float,      # 0 to 1
                "sources": {
                    "reddit": {...},
                    "stocktwits": {...},
                    "news": {...},
                },
                "total_mentions": int,
            }
        """
        sources = {}
        weights = config.SENTIMENT["weights"]

        # Gather sentiment from each source
        if self.reddit:
            try:
                sources["reddit"] = self.reddit.get_sentiment(ticker)
            except Exception as e:
                logger.warning(f"Reddit sentiment failed for {ticker}: {e}")
                sources["reddit"] = {"score": 0.0, "mentions": 0}

        if self.stocktwits:
            try:
                sources["stocktwits"] = self.stocktwits.get_sentiment(ticker)
            except Exception as e:
                logger.warning(f"StockTwits sentiment failed for {ticker}: {e}")
                sources["stocktwits"] = {"score": 0.0, "mentions": 0}

        if self.news:
            try:
                sources["news"] = self.news.get_sentiment(ticker)
            except Exception as e:
                logger.warning(f"News sentiment failed for {ticker}: {e}")
                sources["news"] = {"score": 0.0, "mentions": 0}

        # Calculate weighted combined score
        combined_score = 0.0
        total_weight = 0.0
        total_mentions = 0

        for source_name, source_data in sources.items():
            if source_name in weights and source_data.get("mentions", 0) > 0:
                w = weights[source_name]
                # Weight by both config weight and mention volume
                mention_factor = min(
                    source_data["mentions"] / config.SENTIMENT["min_mentions"],
                    1.0,
                )
                effective_weight = w * mention_factor
                combined_score += source_data["score"] * effective_weight
                total_weight += effective_weight
                total_mentions += source_data.get("mentions", 0)

        if total_weight > 0:
            combined_score /= total_weight

        # Determine signal
        signal = self._score_to_signal(combined_score)

        # Confidence based on data volume and agreement
        confidence = self._calculate_confidence(sources, combined_score)

        result = {
            "ticker": ticker,
            "combined_score": round(combined_score, 4),
            "signal": signal,
            "confidence": round(confidence, 3),
            "sources": sources,
            "total_mentions": total_mentions,
        }

        logger.info(
            f"Combined sentiment for {ticker}: "
            f"score={result['combined_score']}, signal={signal}, "
            f"confidence={result['confidence']}, mentions={total_mentions}"
        )
        return result

    def _score_to_signal(self, score: float) -> str:
        """Convert numeric score to a named signal."""
        thresholds = config.SENTIMENT
        if score >= thresholds["strong_bullish"]:
            return "strong_bullish"
        elif score >= thresholds["bullish"]:
            return "bullish"
        elif score <= thresholds["strong_bearish"]:
            return "strong_bearish"
        elif score <= thresholds["bearish"]:
            return "bearish"
        else:
            return "neutral"

    def _calculate_confidence(
        self, sources: dict, combined_score: float
    ) -> float:
        """
        Calculate confidence (0-1) based on:
        - Number of data points
        - Agreement between sources
        - Strength of signal
        """
        if not sources:
            return 0.0

        scores = [
            s["score"]
            for s in sources.values()
            if s.get("mentions", 0) > 0
        ]

        if not scores:
            return 0.0

        # Factor 1: Data volume (more mentions = more confidence)
        total_mentions = sum(
            s.get("mentions", 0) for s in sources.values()
        )
        volume_factor = min(
            total_mentions / (config.SENTIMENT["min_mentions"] * 3), 1.0
        )

        # Factor 2: Source agreement (all sources agree = higher confidence)
        if len(scores) > 1:
            all_same_direction = all(s > 0 for s in scores) or all(
                s < 0 for s in scores
            )
            agreement_factor = 1.0 if all_same_direction else 0.5
        else:
            agreement_factor = 0.7  # Only one source

        # Factor 3: Signal strength
        strength_factor = min(abs(combined_score) / 0.5, 1.0)

        confidence = (
            volume_factor * 0.3
            + agreement_factor * 0.4
            + strength_factor * 0.3
        )
        return confidence

    def scan_watchlist(self) -> list[dict]:
        """Scan the entire watchlist and return sorted by signal strength."""
        results = []
        for ticker in config.WATCHLIST:
            try:
                result = self.get_combined_sentiment(ticker)
                results.append(result)
            except Exception as e:
                logger.error(f"Error scanning {ticker}: {e}")

        # Sort by absolute signal strength * confidence
        results.sort(
            key=lambda x: abs(x["combined_score"]) * x["confidence"],
            reverse=True,
        )
        return results
