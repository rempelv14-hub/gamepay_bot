from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int = 0) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        return default


def _float(name: str, default: float = 0.0) -> float:
    raw = os.getenv(name, str(default)).strip().replace(',', '.')
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "").strip()
    admin_id: int = _int("ADMIN_ID", 0)
    support_username: str = os.getenv("SUPPORT_USERNAME", "your_support_username").strip().lstrip('@')
    payment_details: str = os.getenv(
        "PAYMENT_DETAILS",
        "Укажите реквизиты в .env: PAYMENT_DETAILS=Kaspi/карта/инструкция оплаты"
    ).strip()
    currency_symbol: str = os.getenv("CURRENCY_SYMBOL", "₸").strip()
    referral_bonus_percent: float = _float("REFERRAL_BONUS_PERCENT", 5.0)
    db_path: str = os.getenv("BOT_DB_PATH", "data/bot.db").strip()
    bot_username: str = os.getenv("BOT_USERNAME", "").strip().lstrip('@')

    # TON auto-payments
    ton_wallet: str = os.getenv("TON_WALLET", "").strip()
    ton_api_key: str = os.getenv("TON_API_KEY", "").strip()
    ton_rate_kzt: float = _float("TON_RATE_KZT", 1200.0)
    ton_check_limit: int = _int("TON_CHECK_LIMIT", 50)


settings = Settings()
