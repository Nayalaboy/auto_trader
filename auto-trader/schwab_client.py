"""
Schwab Trader API Client.
Wraps schwab-py for authentication, market data, and order execution.
"""

import json
from datetime import datetime, timedelta
from typing import Optional

import schwab
from schwab.client import Client
from schwab.orders.options import (
    OptionSymbol,
    bull_call_vertical_close,
    bull_call_vertical_open,
    bear_put_vertical_close,
    bear_put_vertical_open,
    option_buy_to_open_limit,
    option_sell_to_close_limit,
)

import config
from utils.logger import setup_logger

logger = setup_logger("SchwabClient")

TOKEN_PATH = "schwab_token.json"


class SchwabClient:
    """Wrapper for Schwab Trader API."""

    def __init__(self, app_key: str, app_secret: str, callback_url: str):
        self.app_key = app_key
        self.app_secret = app_secret
        self.callback_url = callback_url
        self.client: Optional[Client] = None
        self.account_hash: Optional[str] = None

    def authenticate(self):
        """
        Authenticate with Schwab API.
        First time: opens browser for OAuth flow.
        Subsequent: uses saved token (valid for 7 days).
        """
        try:
            # Try to use existing token
            self.client = schwab.auth.client_from_token_file(
                TOKEN_PATH, self.app_key, self.app_secret
            )
            logger.info("Authenticated using saved token")
        except FileNotFoundError:
            # First time: manual OAuth flow
            logger.info("No saved token found. Starting OAuth flow...")
            self.client = schwab.auth.client_from_manual_flow(
                self.app_key,
                self.app_secret,
                self.callback_url,
                TOKEN_PATH,
            )
            logger.info("Authentication successful, token saved")

        # Get account hash
        resp = self.client.get_account_numbers()
        accounts = resp.json()
        if accounts:
            self.account_hash = accounts[0]["hashValue"]
            logger.info(f"Using account hash: {self.account_hash[:8]}...")
        else:
            raise ValueError("No accounts found")

    def get_account_info(self) -> dict:
        """Get account balances and positions."""
        resp = self.client.get_account(
            self.account_hash,
            fields=[Client.Account.Fields.POSITIONS],
        )
        return resp.json()

    def get_quote(self, ticker: str) -> dict:
        """Get real-time quote for a ticker."""
        resp = self.client.get_quote(ticker)
        return resp.json()

    def get_option_chain(
        self,
        ticker: str,
        contract_type: str = "ALL",
        strike_count: int = 10,
        days_to_expiry: tuple = None,
    ) -> dict:
        """
        Get options chain for a ticker.

        Args:
            ticker: Stock symbol
            contract_type: "CALL", "PUT", or "ALL"
            strike_count: Number of strikes around ATM
            days_to_expiry: (min_dte, max_dte) tuple
        """
        if days_to_expiry is None:
            days_to_expiry = (
                config.RISK["min_days_to_expiry"],
                config.RISK["max_days_to_expiry"],
            )

        from_date = datetime.now() + timedelta(days=days_to_expiry[0])
        to_date = datetime.now() + timedelta(days=days_to_expiry[1])

        contract_map = {
            "CALL": Client.Options.ContractType.CALL,
            "PUT": Client.Options.ContractType.PUT,
            "ALL": Client.Options.ContractType.ALL,
        }

        resp = self.client.get_option_chain(
            ticker,
            contract_type=contract_map.get(contract_type,
                                            Client.Options.ContractType.ALL),
            strike_count=strike_count,
            from_date=from_date,
            to_date=to_date,
        )
        return resp.json()

    def place_option_order(
        self,
        ticker: str,
        contract_symbol: str,
        action: str,
        quantity: int,
        price: float,
        order_type: str = "LIMIT",
    ) -> dict:
        """
        Place a single-leg option order.

        Args:
            ticker: Underlying symbol
            contract_symbol: Full option symbol
            action: "BUY_TO_OPEN" or "SELL_TO_CLOSE"
            quantity: Number of contracts
            price: Limit price per contract
            order_type: "LIMIT" or "MARKET"
        """
        if action == "BUY_TO_OPEN":
            order = option_buy_to_open_limit(
                contract_symbol, quantity, price
            )
        elif action == "SELL_TO_CLOSE":
            order = option_sell_to_close_limit(
                contract_symbol, quantity, price
            )
        else:
            raise ValueError(f"Unknown action: {action}")

        logger.info(
            f"Placing order: {action} {quantity}x {contract_symbol} @ ${price}"
        )

        resp = self.client.place_order(self.account_hash, order)

        # Extract order ID from response headers
        order_id = None
        if resp.status_code == 201:
            location = resp.headers.get("Location", "")
            order_id = location.split("/")[-1] if location else None

        result = {
            "status": "placed" if resp.status_code == 201 else "failed",
            "order_id": order_id,
            "http_status": resp.status_code,
        }

        logger.info(f"Order result: {result}")
        return result

    def place_spread_order(
        self,
        ticker: str,
        long_symbol: str,
        short_symbol: str,
        quantity: int,
        net_debit: float,
        spread_type: str = "bull_call",
    ) -> dict:
        """Place a vertical spread order."""
        if spread_type == "bull_call":
            order = bull_call_vertical_open(
                long_symbol, short_symbol, quantity, net_debit
            )
        elif spread_type == "bear_put":
            order = bear_put_vertical_open(
                long_symbol, short_symbol, quantity, net_debit
            )
        else:
            raise ValueError(f"Unknown spread type: {spread_type}")

        logger.info(
            f"Placing spread: {spread_type} {quantity}x "
            f"long={long_symbol} short={short_symbol} debit=${net_debit}"
        )

        resp = self.client.place_order(self.account_hash, order)
        order_id = None
        if resp.status_code == 201:
            location = resp.headers.get("Location", "")
            order_id = location.split("/")[-1] if location else None

        return {
            "status": "placed" if resp.status_code == 201 else "failed",
            "order_id": order_id,
            "http_status": resp.status_code,
        }

    def get_order_status(self, order_id: str) -> dict:
        """Check the status of an order."""
        resp = self.client.get_order(order_id, self.account_hash)
        return resp.json()

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        resp = self.client.cancel_order(order_id, self.account_hash)
        return resp.status_code == 200

    def get_positions(self) -> list:
        """Get current positions."""
        account = self.get_account_info()
        positions = (
            account.get("securitiesAccount", {}).get("positions", [])
        )
        return positions

    def build_option_symbol(
        self,
        ticker: str,
        expiry: datetime,
        call_or_put: str,
        strike: float,
    ) -> str:
        """Build a Schwab-format option symbol."""
        return OptionSymbol(
            ticker,
            expiry,
            call_or_put[0].upper(),  # 'C' or 'P'
            strike,
        ).build()
