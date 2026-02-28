"""
Signal Generator.
Combines sentiment + technicals + IV to produce actionable trade signals.
"""

from datetime import datetime

import config
from utils.logger import setup_logger

logger = setup_logger("Signals")


class SignalGenerator:
    """Generate trade signals from all data sources."""

    def __init__(
        self, sentiment_aggregator, technical_analyzer, strategy_selector,
        risk_manager, executor
    ):
        self.sentiment = sentiment_aggregator
        self.technicals = technical_analyzer
        self.strategy = strategy_selector
        self.risk_manager = risk_manager
        self.executor = executor

    def scan_and_generate(self) -> list[dict]:
        """
        Scan the watchlist and generate trade signals.

        Returns list of trade signals, sorted by strength.
        """
        logger.info("=" * 60)
        logger.info("Starting watchlist scan...")
        logger.info("=" * 60)

        signals = []

        for ticker in config.WATCHLIST:
            try:
                signal = self._analyze_ticker(ticker)
                if signal:
                    signals.append(signal)
            except Exception as e:
                logger.error(f"Error analyzing {ticker}: {e}")

        # Sort by signal strength
        signals.sort(
            key=lambda x: abs(x["combined_score"]) * x["confidence"],
            reverse=True,
        )

        logger.info(f"Scan complete: {len(signals)} signals generated")
        for s in signals:
            logger.info(
                f"  {s['ticker']}: {s['strategy']} "
                f"(score={s['combined_score']:.2f}, "
                f"conf={s['confidence']:.2f})"
            )

        return signals

    def _analyze_ticker(self, ticker: str) -> dict | None:
        """Analyze a single ticker and generate a signal if warranted."""
        logger.info(f"Analyzing {ticker}...")

        # 1. Get sentiment
        sentiment = self.sentiment.get_combined_sentiment(ticker)

        # 2. Get technicals
        technicals = self.technicals.calculate_indicators(ticker)
        if technicals is None:
            logger.warning(f"No technical data for {ticker}, skipping")
            return None

        # 3. Get IV rank
        iv_rank = self.technicals.get_iv_rank(ticker)
        if iv_rank is None:
            iv_rank = 50.0  # Default to middle if unavailable

        # 4. Calculate combined score
        weights = config.SENTIMENT["weights"]
        combined_score = (
            sentiment["combined_score"] * (1 - weights.get("technical", 0.15))
            + technicals["technical_score"] * weights.get("technical", 0.15)
        )

        # 5. Check if signal is strong enough
        if abs(combined_score) < config.SIGNALS["min_signal_score"]:
            logger.debug(
                f"{ticker}: Signal too weak "
                f"(combined={combined_score:.3f}, "
                f"threshold={config.SIGNALS['min_signal_score']})"
            )
            return None

        # 6. Select strategy
        selected_strategy = self.strategy.select_strategy(
            ticker=ticker,
            sentiment_signal=sentiment["signal"],
            sentiment_score=sentiment["combined_score"],
            confidence=sentiment["confidence"],
            technical_score=technicals["technical_score"],
            iv_rank=iv_rank,
        )

        if selected_strategy is None:
            return None

        # 7. Find specific contracts (if Schwab client available)
        contracts = self.strategy.find_option_contracts(
            ticker, selected_strategy
        )

        # 8. Calculate position size
        quantity = 1  # Default
        if contracts and self.risk_manager:
            try:
                account = self.risk_manager.schwab.get_account_info()
                account_value = (
                    account.get("securitiesAccount", {})
                    .get("currentBalances", {})
                    .get("liquidationValue", 50000)
                )
                price = contracts.get(
                    "mid", contracts.get("net_debit", 1.0)
                )
                quantity = self.risk_manager.calculate_position_size(
                    account_value, price, selected_strategy["strategy"]
                )
            except Exception:
                quantity = 1

        if quantity <= 0:
            logger.info(f"{ticker}: Position size = 0, skipping")
            return None

        signal = {
            "ticker": ticker,
            "timestamp": datetime.now().isoformat(),
            "combined_score": round(combined_score, 4),
            "confidence": sentiment["confidence"],
            "sentiment_score": sentiment["combined_score"],
            "sentiment_signal": sentiment["signal"],
            "technical_score": technicals["technical_score"],
            "price": technicals["price"],
            "rsi": technicals["rsi"],
            "trend": technicals["trend"],
            "iv_rank": iv_rank,
            "strategy": selected_strategy["strategy"],
            "direction": selected_strategy["direction"],
            "reason": selected_strategy["reason"],
            "contracts": contracts or {},
            "quantity": quantity,
            "mentions": sentiment["total_mentions"],
        }

        return signal

    def execute_signals(self, signals: list[dict], max_trades: int = 3):
        """Execute the top N trade signals."""
        # Check if we can trade
        can_trade, reason = self.risk_manager.can_trade()
        if not can_trade:
            logger.warning(f"Cannot trade: {reason}")
            return []

        results = []
        trades_placed = 0

        for signal in signals:
            if trades_placed >= max_trades:
                break

            # Final confirmation log
            logger.info(
                f"\n{'='*50}\n"
                f"EXECUTING: {signal['strategy']} on {signal['ticker']}\n"
                f"Direction: {signal['direction']}\n"
                f"Score: {signal['combined_score']:.3f} "
                f"(Sentiment: {signal['sentiment_score']:.3f}, "
                f"Technical: {signal['technical_score']:.3f})\n"
                f"Confidence: {signal['confidence']:.3f}\n"
                f"IV Rank: {signal['iv_rank']:.1f}\n"
                f"Reason: {signal['reason']}\n"
                f"{'='*50}"
            )

            result = self.executor.execute_trade(signal)
            results.append(result)

            if result.get("status") in ("paper_executed", "live_executed"):
                trades_placed += 1

        return results

    def generate_report(self, signals: list[dict]) -> str:
        """Generate a human-readable analysis report."""
        lines = [
            "=" * 60,
            f"  OPTIONS TRADING BOT - ANALYSIS REPORT",
            f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 60,
            "",
        ]

        if not signals:
            lines.append("No actionable signals found this scan.")
            return "\n".join(lines)

        for i, s in enumerate(signals, 1):
            lines.extend([
                f"--- Signal #{i}: {s['ticker']} ---",
                f"  Strategy:    {s['strategy']} ({s['direction']})",
                f"  Price:       ${s['price']:.2f}",
                f"  Sentiment:   {s['sentiment_signal']} "
                f"({s['sentiment_score']:.3f})",
                f"  Technical:   {s['technical_score']:.3f} "
                f"(RSI: {s['rsi']:.1f}, Trend: {s['trend']})",
                f"  IV Rank:     {s['iv_rank']:.1f}",
                f"  Combined:    {s['combined_score']:.3f} "
                f"(confidence: {s['confidence']:.3f})",
                f"  Mentions:    {s['mentions']}",
                f"  Reason:      {s['reason']}",
                f"  Quantity:    {s['quantity']} contracts",
                "",
            ])

        # Performance summary if available
        perf = self.executor.get_performance_summary()
        if perf.get("total_trades", 0) > 0:
            lines.extend([
                "=" * 60,
                "  PAPER TRADING PERFORMANCE",
                "=" * 60,
                f"  Total Trades:  {perf['total_trades']}",
                f"  Win Rate:      {perf['win_rate']}%",
                f"  Total P&L:     ${perf['total_pnl']:,.2f}",
                f"  Avg Win:       ${perf['avg_win']:,.2f}",
                f"  Avg Loss:      ${perf['avg_loss']:,.2f}",
                "",
            ])

        return "\n".join(lines)
