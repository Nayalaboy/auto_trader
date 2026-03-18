"""
order_executor.py — Order Placement with Safety Guards
-------------------------------------------------------
Wraps Schwab order placement with:
  - Dry-run mode (validates without placing)
  - Position sizing guard (max trade value)
  - Daily loss limit kill switch
  - Full order audit log
"""

import os
import json
import logging
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path

from schwab.client import Client
from schwab.orders.equities import equity_buy_market, equity_sell_market
from schwab.orders.common import OrderType, Duration, Session
from dotenv import load_dotenv

from market_data import get_quote

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────────────
DRY_RUN            = os.getenv("DRY_RUN", "true").lower() == "true"
ACCOUNT_NUMBER     = os.getenv("TRADING_ACCOUNT_NUMBER")
MAX_TRADE_USD      = float(os.getenv("MAX_TRADE_VALUE_USD", 500))
DAILY_LOSS_LIMIT   = float(os.getenv("DAILY_LOSS_LIMIT_PCT", 0.02))
LOG_DIR            = Path("./logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "trades.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


class Side(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"


@dataclass
class TradeSignal:
    symbol:     str
    side:       Side
    quantity:   int
    reason:     str              # Human-readable reason (e.g. "RSI oversold + bullish sentiment")
    confidence: float = 0.0     # 0.0 – 1.0 score from your signal model
    strategy:   str   = "manual"


@dataclass
class TradeResult:
    signal:     TradeSignal
    status:     str              # "DRY_RUN" | "PLACED" | "REJECTED" | "ERROR"
    order_id:   str | None
    message:    str
    timestamp:  str = ""

    def __post_init__(self):
        self.timestamp = datetime.now().isoformat()

    def log_to_file(self):
        log_path = LOG_DIR / f"trade_{datetime.now().strftime('%Y%m%d')}.jsonl"
        with open(log_path, "a") as f:
            f.write(json.dumps(asdict(self), default=str) + "\n")


class RiskGuard:
    """
    Pre-trade risk checks. All checks must pass before an order is sent.
    """

    def __init__(self, client: Client, account_hash: str):
        self.client       = client
        self.account_hash = account_hash
        self._portfolio_value = None

    def _get_portfolio_value(self) -> float:
        if self._portfolio_value is None:
            resp = self.client.get_account(
                self.account_hash,
                fields=[Client.Account.Fields.POSITIONS],
            )
            resp.raise_for_status()
            data = resp.json()
            self._portfolio_value = (
                data.get("securitiesAccount", {})
                    .get("currentBalances", {})
                    .get("liquidationValue", 0.0)
            )
        return self._portfolio_value

    def check_trade_size(self, symbol: str, quantity: int) -> tuple[bool, str]:
        """Block trades that exceed MAX_TRADE_USD."""
        quote     = get_quote(self.client, symbol)
        price     = quote.get("ask") or quote.get("last") or 0
        trade_val = price * quantity

        if trade_val > MAX_TRADE_USD:
            return False, (
                f"Trade value ${trade_val:.2f} exceeds max ${MAX_TRADE_USD:.2f}. "
                f"Reduce quantity to {int(MAX_TRADE_USD // price)} shares."
            )
        return True, f"Trade size OK (${trade_val:.2f})"

    def check_daily_loss(self) -> tuple[bool, str]:
        """Block trading if today's P&L has breached the daily loss limit."""
        # TODO: wire in your actual P&L tracking once you have trade history
        # Placeholder — always passes until you add real P&L tracking
        return True, "Daily loss check passed (not yet implemented)"

    def run_all(self, symbol: str, quantity: int) -> tuple[bool, str]:
        checks = [
            self.check_trade_size(symbol, quantity),
            self.check_daily_loss(),
        ]
        for passed, msg in checks:
            if not passed:
                return False, msg
        return True, "All risk checks passed"


class OrderExecutor:

    def __init__(self, client: Client):
        self.client       = client
        self.account_hash = self._resolve_account_hash()
        self.risk         = RiskGuard(client, self.account_hash)

    def _resolve_account_hash(self) -> str:
        """
        Schwab's API uses a hashed account number for all calls.
        Resolves from TRADING_ACCOUNT_NUMBER env var or picks first account.
        """
        resp = self.client.get_account_numbers()
        resp.raise_for_status()
        accounts = resp.json()

        if not accounts:
            raise RuntimeError("No Schwab accounts linked to this token.")

        if ACCOUNT_NUMBER:
            for acct in accounts:
                if acct.get("accountNumber") == ACCOUNT_NUMBER:
                    log.info(f"Using account: ...{ACCOUNT_NUMBER[-4:]}")
                    return acct["hashValue"]
            raise ValueError(f"Account {ACCOUNT_NUMBER} not found in linked accounts.")

        # Default to first account
        log.info(f"No account specified — defaulting to first linked account.")
        return accounts[0]["hashValue"]

    def execute(self, signal: TradeSignal) -> TradeResult:
        """
        Main entry point. Runs risk checks, then places or dry-runs the order.
        """
        log.info(
            f"{'[DRY RUN] ' if DRY_RUN else ''}Processing signal: "
            f"{signal.side.value} {signal.quantity}x {signal.symbol} | {signal.reason}"
        )

        # ── Risk checks ──────────────────────────────────────────────────────
        ok, msg = self.risk.run_all(signal.symbol, signal.quantity)
        if not ok:
            result = TradeResult(signal=signal, status="REJECTED", order_id=None, message=msg)
            log.warning(f"Trade REJECTED: {msg}")
            result.log_to_file()
            return result

        # ── Build order ──────────────────────────────────────────────────────
        if signal.side == Side.BUY:
            order = equity_buy_market(signal.symbol, signal.quantity)
        else:
            order = equity_sell_market(signal.symbol, signal.quantity)

        # ── Dry run: validate only ───────────────────────────────────────────
        if DRY_RUN:
            resp = self.client.preview_order(self.account_hash, order)
            status = "DRY_RUN"
            order_id = None
            if resp.status_code in (200, 201):
                message = f"Dry run validated OK. Order would be: {signal.side.value} {signal.quantity}x {signal.symbol}"
            else:
                message = f"Dry run validation failed: {resp.status_code} — {resp.text}"
                status = "ERROR"
            log.info(message)

        # ── Live order placement ─────────────────────────────────────────────
        else:
            resp = self.client.place_order(self.account_hash, order)
            if resp.status_code == 201:
                order_id = resp.headers.get("Location", "").split("/")[-1]
                status   = "PLACED"
                message  = f"Order placed. ID: {order_id}"
                log.info(f"✅ {message}")
            else:
                order_id = None
                status   = "ERROR"
                message  = f"Order placement failed: {resp.status_code} — {resp.text}"
                log.error(message)

        result = TradeResult(signal=signal, status=status, order_id=order_id, message=message)
        result.log_to_file()
        return result


# ── Quick test ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from auth import get_client

    client   = get_client()
    executor = OrderExecutor(client)

    # Simulate a signal from your strategy
    signal = TradeSignal(
        symbol     = "SPY",
        side       = Side.BUY,
        quantity   = 1,
        reason     = "RSI oversold (28) + positive sentiment score (0.72)",
        confidence = 0.72,
        strategy   = "rsi_sentiment_v1",
    )

    print(f"\n{'='*55}")
    print(f"  {'DRY RUN MODE' if DRY_RUN else '🚨 LIVE TRADING MODE'}")
    print(f"{'='*55}")

    result = executor.execute(signal)

    print(f"\n📋 Result:")
    print(f"   Status    : {result.status}")
    print(f"   Order ID  : {result.order_id or 'N/A'}")
    print(f"   Message   : {result.message}")
    print(f"   Timestamp : {result.timestamp}")
    print(f"\n   Log saved to: logs/trade_{datetime.now().strftime('%Y%m%d')}.jsonl")
