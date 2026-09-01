"""Local configuration loader. It reads the ignored repository-root .env file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def load_local_environment() -> None:
    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")


def required_setting(name: str) -> str:
    load_local_environment()
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"missing required local environment setting {name}")
    return value
