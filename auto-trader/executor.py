"""
Trade Executor.
Handles the actual execution of trades, including paper trading mode.
"""

import json
import os
from datetime import datetime
from typing import Optional

import config
from utils.logger import setup_logger

logger = setup_logger("Executor")

PAPER_TRADES_FILE = "paper_trades.json"


class TradeExecutor:
    """Execute and track trades."""

    def __init__(self, schwab_client=None, risk_manager=None, mode="paper"):
        self.schwab = schwab_client
        self.risk_manager = risk_manager
        self.mode = mode  # "paper", "live", or "analyze"
        self.paper_trades = self._load_paper_trades()

    def _load_paper_trades(self) -> list:
        """Load paper trading history."""
        if os.path.exists(PAPER_TRADES_FILE):
            with open(PAPER_TRADES_FILE) as f:
                return json.load(f)
        return []

    def _save_paper_trades(self):
        """Save paper trading history."""
        with open(PAPER_TRADES_FILE, "w") as f:
            json.dump(self.paper_trades, f, indent=2, default=str)

    def execute_trade(self, trade_signal: dict) -> dict:
        """
        Execute a trade based on a signal.

        Args:
            trade_signal: {
                "ticker": str,
                "strategy": str,
                "direction": str,
                "contracts": dict,    # Contract details
                "quantity": int,
                "reason": str,
                "sentiment_score": float,
                "technical_score": float,
                "confidence": float,
            }

        Returns:
            Trade result dict
        """
        if self.mode == "analyze":
            logger.info(
                f"[ANALYZE MODE] Would trade: "
                f"{trade_signal['strategy']} on {trade_signal['ticker']}"
            )
            return {"status": "analyzed", "signal": trade_signal}

        if self.mode == "paper":
            return self._paper_trade(trade_signal)

        if self.mode == "live":
            return self._live_trade(trade_signal)

        return {"status": "error", "message": f"Unknown mode: {self.mode}"}

    def _paper_trade(self, signal: dict) -> dict:
        """Simulate a trade in paper trading mode."""
        contracts = signal.get("contracts", {})
        quantity = signal.get("quantity", 1)

        trade = {
            "id": f"PAPER-{len(self.paper_trades) + 1:04d}",
            "timestamp": datetime.now().isoformat(),
            "ticker": signal["ticker"],
            "strategy": signal["strategy"],
            "direction": signal["direction"],
            "quantity": quantity,
            "entry_price": contracts.get("mid", contracts.get("net_debit", 0)),
            "contracts": contracts,
            "sentiment_score": signal.get("sentiment_score", 0),
            "technical_score": signal.get("technical_score", 0),
            "confidence": signal.get("confidence", 0),
            "reason": signal.get("reason", ""),
            "status": "open",
            "pnl": 0.0,
        }

        # Set stop loss and take profit
        if self.risk_manager:
            trade["stop_loss"] = self.risk_manager.get_stop_loss_price(
                trade["entry_price"], trade["strategy"]
            )
            trade["take_profit"] = self.risk_manager.get_take_profit_price(
                trade["entry_price"], trade["strategy"]
            )

        self.paper_trades.append(trade)
        self._save_paper_trades()

        logger.info(
            f"[PAPER TRADE] {trade['id']}: "
            f"{trade['strategy']} {trade['ticker']} "
            f"x{quantity} @ ${trade['entry_price']:.2f} "
            f"| Sentiment: {trade['sentiment_score']:.2f} "
            f"| Reason: {trade['reason'][:80]}"
        )

        return {"status": "paper_executed", "trade": trade}

    def _live_trade(self, signal: dict) -> dict:
        """Execute a real trade via Schwab API."""
        if not self.schwab:
            return {"status": "error", "message": "Schwab client not available"}

        # Final risk check
        if self.risk_manager:
            can_trade, reason = self.risk_manager.can_trade()
            if not can_trade:
                logger.warning(f"Trade blocked by risk manager: {reason}")
                return {"status": "blocked", "reason": reason}

        contracts = signal.get("contracts", {})
        quantity = signal.get("quantity", 1)
        strategy = signal["strategy"]

        try:
            if strategy in ("long_call", "long_put"):
                result = self.schwab.place_option_order(
                    ticker=signal["ticker"],
                    contract_symbol=contracts["symbol"],
                    action="BUY_TO_OPEN",
                    quantity=quantity,
                    price=contracts.get("ask", contracts.get("mid", 0)),
                )
            elif strategy in ("bull_call_spread", "bear_put_spread"):
                spread_type = "bull_call" if "bull" in strategy else "bear_put"
                result = self.schwab.place_spread_order(
                    ticker=signal["ticker"],
                    long_symbol=contracts["long_symbol"],
                    short_symbol=contracts["short_symbol"],
                    quantity=quantity,
                    net_debit=contracts["net_debit"],
                    spread_type=spread_type,
                )
            elif strategy == "cash_secured_put":
                result = self.schwab.place_option_order(
                    ticker=signal["ticker"],
                    contract_symbol=contracts["symbol"],
                    action="BUY_TO_OPEN",  # Selling = sell to open
                    quantity=quantity,
                    price=contracts.get("bid", contracts.get("mid", 0)),
                )
            else:
                return {
                    "status": "error",
                    "message": f"Execution not implemented for {strategy}",
                }

            logger.info(
                f"[LIVE TRADE] {strategy} {signal['ticker']} "
                f"x{quantity} - Result: {result}"
            )
            return {"status": "live_executed", "result": result}

        except Exception as e:
            logger.error(f"Live trade execution failed: {e}")
            return {"status": "error", "message": str(e)}

    def get_open_trades(self) -> list:
        """Get all open paper trades."""
        return [t for t in self.paper_trades if t["status"] == "open"]

    def get_trade_history(self) -> list:
        """Get all paper trades."""
        return self.paper_trades

    def get_performance_summary(self) -> dict:
        """Get paper trading performance summary."""
        closed = [t for t in self.paper_trades if t["status"] == "closed"]

        if not closed:
            return {"trades": 0, "message": "No closed trades yet"}

        total_pnl = sum(t.get("pnl", 0) for t in closed)
        winners = [t for t in closed if t.get("pnl", 0) > 0]
        losers = [t for t in closed if t.get("pnl", 0) < 0]

        return {
            "total_trades": len(closed),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": round(len(winners) / len(closed) * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(
                sum(t["pnl"] for t in winners) / len(winners), 2
            ) if winners else 0,
            "avg_loss": round(
                sum(t["pnl"] for t in losers) / len(losers), 2
            ) if losers else 0,
            "best_trade": max(closed, key=lambda t: t.get("pnl", 0)),
            "worst_trade": min(closed, key=lambda t: t.get("pnl", 0)),
        }
