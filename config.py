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


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, str(int(default))).strip().lower()
    return raw in {"1", "true", "yes", "on", "да"}


def _ids_from_env(name: str) -> tuple[int, ...]:
    raw = os.getenv(name, "").strip()
    ids: list[int] = []
    if not raw:
        return tuple(ids)
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError:
            continue
        if value and value not in ids:
            ids.append(value)
    return tuple(ids)


def _admin_ids() -> tuple[int, ...]:
    ids = list(_ids_from_env("ADMIN_IDS"))
    single = _int("ADMIN_ID", 0)
    if single and single not in ids:
        ids.insert(0, single)
    return tuple(ids)


def _merge_ids(*groups: tuple[int, ...]) -> tuple[int, ...]:
    merged: list[int] = []
    for group in groups:
        for user_id in group:
            if user_id and user_id not in merged:
                merged.append(user_id)
    return tuple(merged)


@dataclass(frozen=True)
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "").strip()

    # Backward compatibility: ADMIN_ID/ADMIN_IDS still work.
    admin_ids_raw: tuple[int, ...] = _admin_ids()

    # Roles. If OWNER_IDS is empty, ADMIN_ID/ADMIN_IDS become owners by default.
    owner_ids_raw: tuple[int, ...] = _ids_from_env("OWNER_IDS")
    manager_ids: tuple[int, ...] = _ids_from_env("MANAGER_IDS")
    support_ids: tuple[int, ...] = _ids_from_env("SUPPORT_IDS")

    support_username: str = os.getenv("SUPPORT_USERNAME", "your_support_username").strip().lstrip('@')
    payment_details: str = os.getenv(
        "PAYMENT_DETAILS",
        "Укажите реквизиты в .env: PAYMENT_DETAILS=Kaspi/карта/инструкция оплаты"
    ).strip()
    # Multi-currency. All internal prices/balances are stored in KZT as the base currency.
    # RUB is converted by RUB_TO_KZT_RATE: how many ₸ equals 1 ₽.
    default_currency: str = os.getenv("DEFAULT_CURRENCY", os.getenv("CURRENCY", "KZT")).strip().upper()
    currency_symbol: str = os.getenv("CURRENCY_SYMBOL", "₸").strip()
    rub_to_kzt_rate: float = _float("RUB_TO_KZT_RATE", 6.0)
    payment_details_kzt: str = os.getenv(
        "PAYMENT_DETAILS_KZT",
        os.getenv("PAYMENT_DETAILS", "Укажите реквизиты для ₸ оплаты: PAYMENT_DETAILS_KZT=...")
    ).strip()
    payment_details_rub: str = os.getenv(
        "PAYMENT_DETAILS_RUB",
        "Укажите реквизиты для ₽ оплаты: PAYMENT_DETAILS_RUB=..."
    ).strip()
    referral_bonus_percent: float = _float("REFERRAL_BONUS_PERCENT", 5.0)
    db_path: str = os.getenv("BOT_DB_PATH", "data/bot.db").strip()
    bot_username: str = os.getenv("BOT_USERNAME", "").strip().lstrip('@')

    # TON auto-payments
    ton_wallet: str = os.getenv("TON_WALLET", "").strip()
    ton_api_key: str = os.getenv("TON_API_KEY", "").strip()
    ton_rate_kzt: float = _float("TON_RATE_KZT", 1200.0)  # fallback/manual rate
    ton_rate_auto_enabled: bool = _bool("TON_RATE_AUTO_ENABLED", False)
    ton_rate_cache_minutes: int = _int("TON_RATE_CACHE_MINUTES", 15)
    ton_check_limit: int = _int("TON_CHECK_LIMIT", 50)
    ton_invoice_ttl_minutes: int = _int("TON_INVOICE_TTL_MINUTES", 30)

    # Safe refunds. Direct on-chain refunds are not enabled: no seed/private key in bot.
    refund_to_balance_enabled: bool = _bool("REFUND_TO_BALANCE_ENABLED", True)

    # Backups
    auto_backup_enabled: bool = _bool("AUTO_BACKUP_ENABLED", False)
    auto_backup_hour: int = _int("AUTO_BACKUP_HOUR", 9)

    @property
    def owner_ids(self) -> tuple[int, ...]:
        return self.owner_ids_raw or self.admin_ids_raw

    @property
    def admin_ids(self) -> tuple[int, ...]:
        return _merge_ids(self.owner_ids, self.manager_ids, self.support_ids, self.admin_ids_raw)

    @property
    def admin_id(self) -> int:
        return self.owner_ids[0] if self.owner_ids else (self.admin_ids[0] if self.admin_ids else 0)


settings = Settings()
