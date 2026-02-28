"""
Options Strategy Selector.
Chooses the optimal options strategy based on sentiment, technicals, and IV.
"""

from datetime import datetime, timedelta
from typing import Optional

import config
from utils.logger import setup_logger

logger = setup_logger("Strategy")


class OptionsStrategySelector:
    """Select the best options strategy based on market conditions."""

    def __init__(self, schwab_client=None):
        self.schwab = schwab_client
        self.cfg = config.STRATEGIES

    def select_strategy(
        self,
        ticker: str,
        sentiment_signal: str,
        sentiment_score: float,
        confidence: float,
        technical_score: float,
        iv_rank: float = 50.0,
    ) -> Optional[dict]:
        """
        Select the best options strategy.

        Args:
            ticker: Stock symbol
            sentiment_signal: "strong_bullish", "bullish", "neutral", etc.
            sentiment_score: Combined sentiment score (-1 to 1)
            confidence: Confidence level (0 to 1)
            technical_score: Technical indicator score (-1 to 1)
            iv_rank: IV Rank (0-100)

        Returns:
            {
                "strategy": str,
                "direction": str,     # "bullish", "bearish", "neutral"
                "reason": str,
                "iv_context": str,    # "high_iv", "low_iv"
                "params": dict,       # Strategy-specific parameters
            }
        """
        # Combine sentiment and technical scores
        combined = (
            sentiment_score * config.SENTIMENT["weights"].get("reddit", 0.3)
            + sentiment_score * config.SENTIMENT["weights"].get("stocktwits", 0.25)
            + sentiment_score * config.SENTIMENT["weights"].get("news", 0.3)
            + technical_score * config.SENTIMENT["weights"].get("technical", 0.15)
        )

        # Determine IV context
        iv_context = "high_iv" if iv_rank >= self.cfg["high_iv_rank"] else "low_iv"

        # Strategy selection logic
        strategy = None

        if sentiment_signal in ("strong_bullish", "bullish"):
            if iv_context == "high_iv":
                # High IV + Bullish = Sell puts or bull put spread
                if "cash_secured_put" in self.cfg["enabled"]:
                    strategy = {
                        "strategy": "cash_secured_put",
                        "direction": "bullish",
                        "reason": (
                            f"Bullish sentiment ({sentiment_score:.2f}) + "
                            f"High IV (rank {iv_rank:.0f}) favors selling premium"
                        ),
                        "iv_context": iv_context,
                        "params": {
                            "delta_target": 0.30,
                            "dte_target": 30,
                        },
                    }
                elif "bull_call_spread" in self.cfg["enabled"]:
                    strategy = {
                        "strategy": "bull_call_spread",
                        "direction": "bullish",
                        "reason": (
                            f"Bullish sentiment + High IV = spread to reduce cost"
                        ),
                        "iv_context": iv_context,
                        "params": {
                            "width": self.cfg["spread_width"],
                            "dte_target": 30,
                        },
                    }
            else:
                # Low IV + Bullish = Buy calls
                if "long_call" in self.cfg["enabled"]:
                    strategy = {
                        "strategy": "long_call",
                        "direction": "bullish",
                        "reason": (
                            f"Bullish sentiment ({sentiment_score:.2f}) + "
                            f"Low IV (rank {iv_rank:.0f}) = cheap options"
                        ),
                        "iv_context": iv_context,
                        "params": {
                            "delta_range": self.cfg["long_option_delta"],
                            "dte_target": 30,
                        },
                    }

        elif sentiment_signal in ("strong_bearish", "bearish"):
            if iv_context == "high_iv":
                # High IV + Bearish = Bear call spread (sell premium)
                if "bear_put_spread" in self.cfg["enabled"]:
                    strategy = {
                        "strategy": "bear_put_spread",
                        "direction": "bearish",
                        "reason": (
                            f"Bearish sentiment ({sentiment_score:.2f}) + "
                            f"High IV = spread to manage risk"
                        ),
                        "iv_context": iv_context,
                        "params": {
                            "width": self.cfg["spread_width"],
                            "dte_target": 30,
                        },
                    }
            else:
                # Low IV + Bearish = Buy puts
                if "long_put" in self.cfg["enabled"]:
                    strategy = {
                        "strategy": "long_put",
                        "direction": "bearish",
                        "reason": (
                            f"Bearish sentiment ({sentiment_score:.2f}) + "
                            f"Low IV (rank {iv_rank:.0f}) = cheap puts"
                        ),
                        "iv_context": iv_context,
                        "params": {
                            "delta_range": self.cfg["long_option_delta"],
                            "dte_target": 30,
                        },
                    }

        elif sentiment_signal == "neutral":
            if iv_context == "high_iv" and "iron_condor" in self.cfg["enabled"]:
                strategy = {
                    "strategy": "iron_condor",
                    "direction": "neutral",
                    "reason": (
                        f"Neutral sentiment + High IV (rank {iv_rank:.0f}) "
                        f"= sell volatility with iron condor"
                    ),
                    "iv_context": iv_context,
                    "params": {
                        "delta_range": self.cfg["iron_condor_delta"],
                        "dte_target": 30,
                    },
                }

        if strategy is None:
            logger.info(
                f"No strategy selected for {ticker} "
                f"(signal={sentiment_signal}, IV rank={iv_rank})"
            )

        return strategy

    def find_option_contracts(
        self, ticker: str, strategy: dict
    ) -> Optional[dict]:
        """
        Find specific option contracts for the selected strategy.
        Requires an active Schwab client connection.
        """
        if not self.schwab:
            logger.warning("No Schwab client available for contract lookup")
            return None

        try:
            chain = self.schwab.get_option_chain(
                ticker,
                contract_type="CALL" if "call" in strategy["strategy"] else "PUT",
                strike_count=15,
            )

            if not chain or chain.get("status") == "FAILED":
                return None

            # Parse the chain to find best contracts
            # This is simplified - production code would be more sophisticated
            strategy_name = strategy["strategy"]

            if strategy_name == "long_call":
                return self._find_long_option(chain, "call", strategy["params"])
            elif strategy_name == "long_put":
                return self._find_long_option(chain, "put", strategy["params"])
            elif strategy_name == "bull_call_spread":
                return self._find_vertical_spread(
                    chain, "bull_call", strategy["params"]
                )
            elif strategy_name == "bear_put_spread":
                return self._find_vertical_spread(
                    chain, "bear_put", strategy["params"]
                )
            elif strategy_name == "cash_secured_put":
                return self._find_long_option(chain, "put", strategy["params"])
            else:
                logger.warning(f"Contract finder not implemented for {strategy_name}")
                return None

        except Exception as e:
            logger.error(f"Error finding contracts for {ticker}: {e}")
            return None

    def _find_long_option(
        self, chain: dict, option_type: str, params: dict
    ) -> Optional[dict]:
        """Find a single option contract matching criteria."""
        key = "callExpDateMap" if option_type == "call" else "putExpDateMap"
        exp_map = chain.get(key, {})

        best_contract = None
        best_score = -1

        for exp_date, strikes in exp_map.items():
            for strike_price, contracts in strikes.items():
                for contract in contracts:
                    delta = abs(contract.get("delta", 0))
                    oi = contract.get("openInterest", 0)
                    vol = contract.get("totalVolume", 0)
                    dte = contract.get("daysToExpiration", 0)

                    # Check minimum liquidity
                    if oi < self.cfg["min_open_interest"]:
                        continue
                    if vol < self.cfg["min_volume"]:
                        continue

                    # Score based on delta target
                    delta_range = params.get(
                        "delta_range", self.cfg["long_option_delta"]
                    )
                    if delta_range[0] <= delta <= delta_range[1]:
                        # Prefer higher liquidity
                        score = oi * 0.5 + vol * 0.5
                        if score > best_score:
                            best_score = score
                            best_contract = {
                                "symbol": contract.get("symbol"),
                                "strike": float(strike_price),
                                "expiry": exp_date.split(":")[0],
                                "delta": delta,
                                "ask": contract.get("ask", 0),
                                "bid": contract.get("bid", 0),
                                "mid": (
                                    contract.get("ask", 0)
                                    + contract.get("bid", 0)
                                ) / 2,
                                "open_interest": oi,
                                "volume": vol,
                                "dte": dte,
                                "iv": contract.get(
                                    "volatility", 0
                                ),
                            }

        return best_contract

    def _find_vertical_spread(
        self, chain: dict, spread_type: str, params: dict
    ) -> Optional[dict]:
        """Find contracts for a vertical spread."""
        # Simplified: find two contracts with specified width
        width = params.get("width", self.cfg["spread_width"])

        if "call" in spread_type:
            key = "callExpDateMap"
        else:
            key = "putExpDateMap"

        exp_map = chain.get(key, {})

        for exp_date, strikes in exp_map.items():
            strike_prices = sorted([float(s) for s in strikes.keys()])

            for i, long_strike in enumerate(strike_prices):
                short_strike = long_strike + width
                if str(short_strike) in strikes or str(int(short_strike)) in strikes:
                    long_contracts = strikes.get(
                        str(long_strike), strikes.get(str(int(long_strike)), [])
                    )
                    short_contracts = strikes.get(
                        str(short_strike), strikes.get(str(int(short_strike)), [])
                    )

                    if long_contracts and short_contracts:
                        long_c = long_contracts[0]
                        short_c = short_contracts[0]

                        return {
                            "long_symbol": long_c.get("symbol"),
                            "short_symbol": short_c.get("symbol"),
                            "long_strike": long_strike,
                            "short_strike": short_strike,
                            "expiry": exp_date.split(":")[0],
                            "net_debit": round(
                                long_c.get("ask", 0) - short_c.get("bid", 0), 2
                            ),
                            "max_profit": round(
                                width - (long_c.get("ask", 0) - short_c.get("bid", 0)),
                                2,
                            ),
                        }

        return None
