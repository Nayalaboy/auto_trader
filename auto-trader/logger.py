"""Logging utilities for the trading bot."""

import logging
import os
from logging.handlers import RotatingFileHandler

import colorlog

import config


def setup_logger(name: str = "TradingBot") -> logging.Logger:
    """Set up a logger with colored console output and file output."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, config.LOGGING["level"]))

    if logger.handlers:
        return logger

    # Console handler with colors
    console_handler = colorlog.StreamHandler()
    console_handler.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        },
    ))
    logger.addHandler(console_handler)

    # File handler with rotation
    log_dir = os.path.dirname(config.LOGGING["file"])
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    file_handler = RotatingFileHandler(
        config.LOGGING["file"],
        maxBytes=config.LOGGING["max_size_mb"] * 1024 * 1024,
        backupCount=config.LOGGING["backup_count"],
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(file_handler)

    return logger
