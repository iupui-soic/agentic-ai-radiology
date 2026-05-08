"""Structured logging helpers — matches po-adk-python markers."""

from __future__ import annotations

import logging
import os
import sys


def configure_logging(package_name: str = "critcom") -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger(package_name).setLevel(level)
