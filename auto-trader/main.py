#!/usr/bin/env python3
"""
Automated Options Trading Bot
Combines social sentiment + technical analysis + Schwab API execution.

Usage:
    python main.py --mode paper     # Paper trading (default, recommended)
    python main.py --mode live      # Live trading (use with caution!)
    python main.py --mode analyze   # Analysis only, no trades
    python main.py --scan-once      # Run a single scan and exit
"""

import argparse
import os
import sys
import time
from datetime import datetime

import schedule
from dotenv import load_dotenv

import config
from sentiment.aggregator import SentimentAggregator
from sentiment.news_sentiment import NewsSentiment
from sentiment.reddit_sentiment import RedditSentiment
from sentiment.stocktwits import StockTwitsSentiment
from signals.signal_generator import SignalGenerator
from technicals.indicators import TechnicalAnalyzer
from trading.executor import TradeExecutor
from trading.options_strategy import OptionsStrategySelector
from trading.risk_manager import RiskManager
from trading.schwab_client import SchwabClient
from utils.logger import setup_logger

logger = setup_logger("Main")


def is_market_hours() -> bool:
    """Check if the market is currently open (Eastern Time)."""
    from datetime import timezone, timedelta
    eastern = timezone(timedelta(hours=-5))
    now = datetime.now(eastern)

    # Weekday check (0=Mon, 6=Sun)
    if now.weekday() >= 5:
        return False

    market_open = now.replace(
        hour=int(config.SIGNALS["market_open"].split(":")[0]),
        minute=int(config.SIGNALS["market_open"].split(":")[1]),
        second=0,
    )
    market_close = now.replace(
        hour=int(config.SIGNALS["market_close"].split(":")[0]),
        minute=int(config.SIGNALS["market_close"].split(":")[1]),
        second=0,
    )

    return market_open <= now <= market_close


def build_components(mode: str) -> dict:
    """Initialize all bot components."""
    load_dotenv()

    logger.info("Initializing components...")

    # --- Sentiment Sources ---
    reddit = None
    try:
        reddit = RedditSentiment(
            client_id=os.getenv("REDDIT_CLIENT_ID", ""),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET", ""),
            user_agent=os.getenv("REDDIT_USER_AGENT", "OptionsTradingBot/1.0"),
        )
        logger.info("✓ Reddit sentiment initialized")
    except Exception as e:
        logger.warning(f"✗ Reddit sentiment unavailable: {e}")

    stocktwits = None
    try:
        stocktwits = StockTwitsSentiment()
        logger.info("✓ StockTwits sentiment initialized")
    except Exception as e:
        logger.warning(f"✗ StockTwits unavailable: {e}")

    news = None
    try:
        news = NewsSentiment(newsapi_key=os.getenv("NEWSAPI_KEY", ""))
        logger.info("✓ News sentiment initialized")
    except Exception as e:
        logger.warning(f"✗ News sentiment unavailable: {e}")

    # --- Sentiment Aggregator ---
    aggregator = SentimentAggregator(
        reddit=reddit, stocktwits=stocktwits, news=news
    )

    # --- Technical Analyzer ---
    technicals = TechnicalAnalyzer()
    logger.info("✓ Technical analyzer initialized")

    # --- Schwab Client (optional for paper/analyze mode) ---
    schwab = None
    if mode == "live" or os.getenv("SCHWAB_APP_KEY"):
        try:
            schwab = SchwabClient(
                app_key=os.getenv("SCHWAB_APP_KEY", ""),
                app_secret=os.getenv("SCHWAB_APP_SECRET", ""),
                callback_url=os.getenv(
                    "SCHWAB_CALLBACK_URL", "https://127.0.0.1:8080/callback"
                ),
            )
            schwab.authenticate()
            logger.info("✓ Schwab API authenticated")
        except Exception as e:
            if mode == "live":
                logger.critical(f"Schwab authentication failed: {e}")
                sys.exit(1)
            else:
                logger.warning(
                    f"✗ Schwab API unavailable (OK for {mode} mode): {e}"
                )
                schwab = None

    # --- Risk Manager ---
    risk_manager = RiskManager(schwab_client=schwab)

    # --- Strategy Selector ---
    strategy_selector = OptionsStrategySelector(schwab_client=schwab)

    # --- Executor ---
    executor = TradeExecutor(
        schwab_client=schwab, risk_manager=risk_manager, mode=mode
    )

    # --- Signal Generator ---
    signal_gen = SignalGenerator(
        sentiment_aggregator=aggregator,
        technical_analyzer=technicals,
        strategy_selector=strategy_selector,
        risk_manager=risk_manager,
        executor=executor,
    )

    return {
        "signal_gen": signal_gen,
        "executor": executor,
        "risk_manager": risk_manager,
    }


def run_scan(components: dict, execute: bool = True):
    """Run a single scan of the watchlist."""
    signal_gen = components["signal_gen"]

    logger.info("\n" + "=" * 60)
    logger.info(f"SCAN STARTED at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Watchlist: {', '.join(config.WATCHLIST)}")
    logger.info("=" * 60)

    # Generate signals
    signals = signal_gen.scan_and_generate()

    # Print report
    report = signal_gen.generate_report(signals)
    print(report)

    # Execute trades if signals found and execution is enabled
    if execute and signals:
        if not is_market_hours():
            logger.info("Market is closed — logging signals but not executing")
        else:
            results = signal_gen.execute_signals(signals)
            for r in results:
                logger.info(f"Trade result: {r}")

    return signals


def main():
    parser = argparse.ArgumentParser(
        description="Automated Options Trading Bot"
    )
    parser.add_argument(
        "--mode",
        choices=["paper", "live", "analyze"],
        default=os.getenv("TRADING_MODE", "paper"),
        help="Trading mode (default: paper)",
    )
    parser.add_argument(
        "--scan-once",
        action="store_true",
        help="Run a single scan and exit",
    )
    args = parser.parse_args()

    # Safety warning for live mode
    if args.mode == "live":
        print("\n" + "!" * 60)
        print("  WARNING: LIVE TRADING MODE")
        print("  Real money will be used. Are you sure?")
        print("!" * 60)
        confirm = input("Type 'YES I UNDERSTAND THE RISKS' to continue: ")
        if confirm != "YES I UNDERSTAND THE RISKS":
            print("Aborting.")
            sys.exit(0)

    logger.info(f"Starting bot in {args.mode.upper()} mode")
    components = build_components(args.mode)

    if args.scan_once:
        run_scan(components, execute=(args.mode != "analyze"))
        return

    # Schedule recurring scans
    interval = config.SIGNALS["scan_interval_minutes"]
    logger.info(f"Scheduling scans every {interval} minutes")

    schedule.every(interval).minutes.do(
        run_scan, components=components, execute=(args.mode != "analyze")
    )

    # Run first scan immediately
    run_scan(components, execute=(args.mode != "analyze"))

    # Keep running
    logger.info("Bot is running. Press Ctrl+C to stop.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")

        # Print final performance summary
        perf = components["executor"].get_performance_summary()
        if perf.get("total_trades", 0) > 0:
            logger.info(f"Final performance: {perf}")


if __name__ == "__main__":
    main()
