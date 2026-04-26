from __future__ import annotations

import re

from config import settings

SUPPORTED_CURRENCIES = {
    "KZT": {"symbol": "₸", "name": "тенге", "short": "тг"},
    "RUB": {"symbol": "₽", "name": "рубли", "short": "руб."},
}


def normalize_currency(currency: str | None) -> str:
    code = (currency or settings.default_currency or "KZT").strip().upper()
    return code if code in SUPPORTED_CURRENCIES else "KZT"


def currency_symbol(currency: str | None) -> str:
    return SUPPORTED_CURRENCIES[normalize_currency(currency)]["symbol"]


def currency_name(currency: str | None) -> str:
    return SUPPORTED_CURRENCIES[normalize_currency(currency)]["name"]


def amount_to_kzt(amount: float, currency: str | None) -> float:
    code = normalize_currency(currency)
    value = float(amount)
    if code == "RUB":
        return round(value * float(settings.rub_to_kzt_rate), 2)
    return round(value, 2)


def kzt_to_currency(amount_kzt: float, currency: str | None) -> float:
    code = normalize_currency(currency)
    value = float(amount_kzt)
    if code == "RUB":
        rate = float(settings.rub_to_kzt_rate) or 1.0
        return round(value / rate, 2)
    return round(value, 2)


def _fmt_number(value: float) -> str:
    value = round(float(value), 2)
    if value.is_integer():
        return f"{int(value):,}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def format_money(amount_kzt: float | int, currency: str | None = None) -> str:
    code = normalize_currency(currency)
    value = kzt_to_currency(float(amount_kzt), code)
    return f"{_fmt_number(value)}{currency_symbol(code)}"


def format_money_multi(amount_kzt: float | int) -> str:
    return f"{format_money(float(amount_kzt), 'KZT')} / {format_money(float(amount_kzt), 'RUB')}"


def parse_amount(text: str, default_currency: str | None = None) -> tuple[float, str, float]:
    """Return (amount_kzt, detected_currency, original_amount)."""
    raw = (text or "").strip().lower()
    currency = normalize_currency(default_currency)

    if any(token in raw for token in ("₽", "руб", "rub", "р.")):
        currency = "RUB"
    elif any(token in raw for token in ("₸", "тг", "тенге", "kzt")):
        currency = "KZT"

    match = re.search(r"\d+(?:[\s_]*\d{3})*(?:[\.,]\d+)?|\d+(?:[\.,]\d+)?", raw)
    if not match:
        raise ValueError("amount not found")
    number = match.group(0).replace(" ", "").replace("_", "").replace(",", ".")
    amount_original = float(number)
    if amount_original <= 0:
        raise ValueError("amount must be positive")
    return amount_to_kzt(amount_original, currency), currency, amount_original


def payment_details_for(currency: str | None) -> str:
    code = normalize_currency(currency)
    if code == "RUB":
        return settings.payment_details_rub
    return settings.payment_details_kzt
