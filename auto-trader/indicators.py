"""
Technical Analysis Module.
Calculates indicators using price data from yfinance.
"""

from typing import Optional

import numpy as np
import pandas as pd
import ta
import yfinance as yf

import config
from utils.logger import setup_logger

logger = setup_logger("Technicals")


class TechnicalAnalyzer:
    """Calculate technical indicators for stocks."""

    def __init__(self):
        self.cfg = config.TECHNICALS

    def get_data(self, ticker: str, period: str = "3mo") -> Optional[pd.DataFrame]:
        """Fetch historical price data."""
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period=period, interval="1d")
            if df.empty:
                logger.warning(f"No data for {ticker}")
                return None
            return df
        except Exception as e:
            logger.error(f"Error fetching data for {ticker}: {e}")
            return None

    def calculate_indicators(self, ticker: str) -> Optional[dict]:
        """
        Calculate all technical indicators for a ticker.

        Returns:
            {
                "ticker": str,
                "price": float,
                "rsi": float,
                "rsi_signal": str,
                "macd": float,
                "macd_signal_line": float,
                "macd_histogram": float,
                "macd_crossover": str,
                "bb_upper": float,
                "bb_middle": float,
                "bb_lower": float,
                "bb_position": str,
                "sma_20": float,
                "sma_50": float,
                "trend": str,
                "volume_ratio": float,
                "technical_score": float,  # -1 to +1
            }
        """
        df = self.get_data(ticker)
        if df is None or len(df) < 50:
            return None

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]
        current_price = close.iloc[-1]

        # RSI
        rsi = ta.momentum.RSIIndicator(
            close, window=self.cfg["rsi_period"]
        ).rsi().iloc[-1]

        rsi_signal = "neutral"
        if rsi >= self.cfg["rsi_overbought"]:
            rsi_signal = "overbought"
        elif rsi <= self.cfg["rsi_oversold"]:
            rsi_signal = "oversold"

        # MACD
        macd_ind = ta.trend.MACD(
            close,
            window_slow=self.cfg["macd_slow"],
            window_fast=self.cfg["macd_fast"],
            window_sign=self.cfg["macd_signal"],
        )
        macd_val = macd_ind.macd().iloc[-1]
        macd_signal = macd_ind.macd_signal().iloc[-1]
        macd_hist = macd_ind.macd_diff().iloc[-1]
        macd_hist_prev = macd_ind.macd_diff().iloc[-2]

        macd_crossover = "none"
        if macd_hist > 0 and macd_hist_prev <= 0:
            macd_crossover = "bullish"
        elif macd_hist < 0 and macd_hist_prev >= 0:
            macd_crossover = "bearish"

        # Bollinger Bands
        bb = ta.volatility.BollingerBands(
            close,
            window=self.cfg["bb_period"],
            window_dev=self.cfg["bb_std"],
        )
        bb_upper = bb.bollinger_hband().iloc[-1]
        bb_middle = bb.bollinger_mavg().iloc[-1]
        bb_lower = bb.bollinger_lband().iloc[-1]

        bb_position = "middle"
        if current_price >= bb_upper:
            bb_position = "above_upper"
        elif current_price <= bb_lower:
            bb_position = "below_lower"
        elif current_price > bb_middle:
            bb_position = "upper_half"
        else:
            bb_position = "lower_half"

        # SMAs
        sma_20 = close.rolling(window=self.cfg["sma_short"]).mean().iloc[-1]
        sma_50 = close.rolling(window=self.cfg["sma_long"]).mean().iloc[-1]

        trend = "neutral"
        if sma_20 > sma_50 and current_price > sma_20:
            trend = "bullish"
        elif sma_20 < sma_50 and current_price < sma_20:
            trend = "bearish"

        # Volume ratio (current vs average)
        avg_volume = volume.rolling(
            window=self.cfg["volume_avg_period"]
        ).mean().iloc[-1]
        volume_ratio = volume.iloc[-1] / avg_volume if avg_volume > 0 else 1.0

        # Calculate composite technical score (-1 to +1)
        technical_score = self._calculate_score(
            rsi, rsi_signal, macd_hist, macd_crossover,
            bb_position, trend, volume_ratio
        )

        result = {
            "ticker": ticker,
            "price": round(current_price, 2),
            "rsi": round(rsi, 2),
            "rsi_signal": rsi_signal,
            "macd": round(macd_val, 4),
            "macd_signal_line": round(macd_signal, 4),
            "macd_histogram": round(macd_hist, 4),
            "macd_crossover": macd_crossover,
            "bb_upper": round(bb_upper, 2),
            "bb_middle": round(bb_middle, 2),
            "bb_lower": round(bb_lower, 2),
            "bb_position": bb_position,
            "sma_20": round(sma_20, 2),
            "sma_50": round(sma_50, 2),
            "trend": trend,
            "volume_ratio": round(volume_ratio, 2),
            "technical_score": round(technical_score, 4),
        }

        logger.info(
            f"Technicals for {ticker}: price={result['price']}, "
            f"RSI={result['rsi']}, trend={trend}, score={result['technical_score']}"
        )
        return result

    def _calculate_score(
        self, rsi, rsi_signal, macd_hist, macd_crossover,
        bb_position, trend, volume_ratio
    ) -> float:
        """Combine indicators into a single score from -1 to +1."""
        score = 0.0

        # RSI component (weight: 0.25)
        if rsi_signal == "oversold":
            score += 0.25  # Potential bounce
        elif rsi_signal == "overbought":
            score -= 0.25  # Potential pullback
        else:
            # Linear scale between 30-70
            rsi_normalized = (rsi - 50) / 50  # -0.4 to +0.4
            score += rsi_normalized * 0.15

        # MACD component (weight: 0.25)
        if macd_crossover == "bullish":
            score += 0.25
        elif macd_crossover == "bearish":
            score -= 0.25
        else:
            # Use histogram direction
            if macd_hist > 0:
                score += 0.1
            elif macd_hist < 0:
                score -= 0.1

        # Bollinger Band component (weight: 0.2)
        bb_scores = {
            "below_lower": 0.2,    # Oversold, potential bounce
            "lower_half": 0.05,
            "upper_half": -0.05,
            "above_upper": -0.2,   # Overbought
        }
        score += bb_scores.get(bb_position, 0)

        # Trend component (weight: 0.2)
        trend_scores = {"bullish": 0.2, "bearish": -0.2, "neutral": 0}
        score += trend_scores[trend]

        # Volume confirmation (weight: 0.1)
        if volume_ratio > 1.5:
            # High volume confirms the trend direction
            score *= 1.1
        elif volume_ratio < 0.5:
            # Low volume weakens the signal
            score *= 0.8

        return max(-1.0, min(1.0, score))

    def get_iv_rank(self, ticker: str) -> Optional[float]:
        """
        Estimate IV Rank (0-100) using historical volatility.
        Note: For precise IV rank, you'd need options chain data from Schwab.
        """
        df = self.get_data(ticker, period="1y")
        if df is None or len(df) < 60:
            return None

        # Calculate historical volatility (20-day rolling)
        returns = np.log(df["Close"] / df["Close"].shift(1))
        hv = returns.rolling(window=20).std() * np.sqrt(252) * 100

        current_hv = hv.iloc[-1]
        hv_min = hv.min()
        hv_max = hv.max()

        if hv_max == hv_min:
            return 50.0

        iv_rank = (current_hv - hv_min) / (hv_max - hv_min) * 100
        return round(iv_rank, 1)
