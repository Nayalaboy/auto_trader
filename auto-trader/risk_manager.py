"""
Risk Management Module.
Enforces position sizing, stop losses, and portfolio-level risk limits.
"""

from datetime import datetime

import config
from utils.logger import setup_logger

logger = setup_logger("RiskManager")


class RiskManager:
    """Enforce risk management rules on all trades."""

    def __init__(self, schwab_client=None):
        self.schwab = schwab_client
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.last_reset_date = datetime.now().date()
        self.cfg = config.RISK

    def _reset_daily_if_needed(self):
        """Reset daily counters at start of new day."""
        today = datetime.now().date()
        if today != self.last_reset_date:
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.last_reset_date = today

    def can_trade(self) -> tuple[bool, str]:
        """
        Check if we're allowed to enter a new trade.

        Returns:
            (allowed: bool, reason: str)
        """
        self._reset_daily_if_needed()

        # Check daily loss limit
        if self.schwab:
            try:
                account = self.schwab.get_account_info()
                balance_info = account.get("securitiesAccount", {})

                current_balance = balance_info.get(
                    "currentBalances", {}
                ).get("liquidationValue", 0)

                # Check minimum balance
                if current_balance < self.cfg["min_account_balance"]:
                    return False, (
                        f"Account balance (${current_balance:,.0f}) "
                        f"below minimum (${self.cfg['min_account_balance']:,.0f})"
                    )

                # Check open positions
                positions = balance_info.get("positions", [])
                option_positions = [
                    p for p in positions
                    if p.get("instrument", {}).get("assetType") == "OPTION"
                ]

                if len(option_positions) >= self.cfg["max_open_positions"]:
                    return False, (
                        f"Max open positions reached "
                        f"({len(option_positions)}/{self.cfg['max_open_positions']})"
                    )

            except Exception as e:
                logger.warning(f"Could not check account status: {e}")

        return True, "OK"

    def calculate_position_size(
        self,
        account_value: float,
        option_price: float,
        strategy: str,
    ) -> int:
        """
        Calculate how many contracts to buy based on risk limits.

        Args:
            account_value: Total portfolio value
            option_price: Price per contract (premium)
            strategy: Name of the strategy

        Returns:
            Number of contracts (0 if trade should be skipped)
        """
        max_risk_amount = account_value * (
            self.cfg["max_single_trade_risk_pct"] / 100
        )

        # For long options, max loss = premium paid
        if strategy in ("long_call", "long_put"):
            cost_per_contract = option_price * 100  # Options are 100 shares
            if cost_per_contract <= 0:
                return 0
            contracts = int(max_risk_amount / cost_per_contract)

        # For spreads, max loss = net debit * 100
        elif strategy in ("bull_call_spread", "bear_put_spread"):
            cost_per_contract = option_price * 100
            if cost_per_contract <= 0:
                return 0
            contracts = int(max_risk_amount / cost_per_contract)

        # For cash-secured puts, need cash to cover assignment
        elif strategy == "cash_secured_put":
            contracts = int(max_risk_amount / (option_price * 100))

        # For iron condors, max loss = width - credit
        elif strategy == "iron_condor":
            contracts = int(max_risk_amount / (option_price * 100))

        else:
            contracts = 1

        # Never more than a reasonable number
        contracts = max(0, min(contracts, 10))

        logger.info(
            f"Position size: {contracts} contracts "
            f"(account=${account_value:,.0f}, "
            f"max_risk=${max_risk_amount:,.0f}, "
            f"cost/contract=${option_price * 100:,.0f})"
        )
        return contracts

    def get_stop_loss_price(
        self, entry_price: float, strategy: str
    ) -> float:
        """Calculate stop loss price for a position."""
        stop_pct = self.cfg["default_stop_loss_pct"] / 100
        return round(entry_price * (1 - stop_pct), 2)

    def get_take_profit_price(
        self, entry_price: float, strategy: str
    ) -> float:
        """Calculate take profit price for a position."""
        tp_pct = self.cfg["default_take_profit_pct"] / 100
        return round(entry_price * (1 + tp_pct), 2)

    def should_close_position(
        self,
        entry_price: float,
        current_price: float,
        dte: int,
        strategy: str,
    ) -> tuple[bool, str]:
        """
        Check if a position should be closed.

        Returns:
            (should_close: bool, reason: str)
        """
        pnl_pct = (current_price - entry_price) / entry_price * 100

        # Stop loss hit
        if pnl_pct <= -self.cfg["default_stop_loss_pct"]:
            return True, f"Stop loss hit ({pnl_pct:.1f}% loss)"

        # Take profit hit
        if pnl_pct >= self.cfg["default_take_profit_pct"]:
            return True, f"Take profit hit ({pnl_pct:.1f}% gain)"

        # Close before expiration to avoid assignment risk
        if dte <= 1:
            return True, f"Approaching expiration (DTE={dte})"

        # For sold options: close at 50% of max profit
        if strategy in ("cash_secured_put", "iron_condor"):
            if pnl_pct >= 50:
                return True, f"50% of max profit reached ({pnl_pct:.1f}%)"

        return False, "Hold"

    def update_daily_pnl(self, pnl: float):
        """Update daily P&L tracking."""
        self._reset_daily_if_needed()
        self.daily_pnl += pnl
        self.daily_trades += 1

        if self.schwab:
            try:
                account = self.schwab.get_account_info()
                balance = (
                    account.get("securitiesAccount", {})
                    .get("currentBalances", {})
                    .get("liquidationValue", 100000)
                )
                daily_loss_pct = abs(self.daily_pnl) / balance * 100

                if (
                    self.daily_pnl < 0
                    and daily_loss_pct >= self.cfg["max_daily_loss_pct"]
                ):
                    logger.critical(
                        f"DAILY LOSS LIMIT REACHED: "
                        f"${self.daily_pnl:,.2f} ({daily_loss_pct:.1f}%)"
                    )
            except Exception:
                pass
