from __future__ import annotations

import base64
import json
import math
import urllib.parse
import urllib.request
from typing import Any

from config import settings
from database import is_ton_tx_used

NANO = 1_000_000_000


def ton_is_configured() -> bool:
    return bool(settings.ton_wallet and settings.ton_api_key and settings.ton_rate_kzt > 0)


def kzt_to_ton(amount_kzt: float) -> float:
    # Округляем вверх до 0.001 TON, чтобы клиент не отправил меньше нужного.
    raw = float(amount_kzt) / float(settings.ton_rate_kzt)
    return math.ceil(raw * 1000) / 1000


def ton_invoice_comment(order_id: int, user_id: int) -> str:
    return f"GP{order_id}-{str(user_id)[-4:]}"


def _decode_comment(in_msg: dict[str, Any]) -> str:
    if not in_msg:
        return ""

    # TON Center часто кладёт комментарий сюда.
    message = in_msg.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()

    msg_data = in_msg.get("msg_data") or {}
    if isinstance(msg_data, dict):
        text = msg_data.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        body = msg_data.get("body")
        if isinstance(body, str) and body:
            try:
                raw = base64.b64decode(body + "===")
                # У текстового комментария первые 4 байта обычно нули.
                if len(raw) >= 4 and raw[:4] == b"\x00\x00\x00\x00":
                    raw = raw[4:]
                return raw.decode("utf-8", errors="ignore").strip("\x00\n\r ")
            except Exception:
                return ""

    return ""


def _tx_hash(tx: dict[str, Any]) -> str:
    tx_id = tx.get("transaction_id") or {}
    if isinstance(tx_id, dict):
        value = tx_id.get("hash") or tx_id.get("lt")
        if value:
            return str(value)
    return str(tx.get("hash") or tx.get("utime") or json.dumps(tx, sort_keys=True)[:80])


def _load_recent_transactions() -> list[dict[str, Any]]:
    if not ton_is_configured():
        return []

    query = urllib.parse.urlencode({
        "address": settings.ton_wallet,
        "limit": settings.ton_check_limit,
    })
    url = f"https://toncenter.com/api/v2/getTransactions?{query}"
    request = urllib.request.Request(url, headers={"X-API-Key": settings.ton_api_key})

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    if not data.get("ok"):
        return []
    result = data.get("result")
    return result if isinstance(result, list) else []


def find_ton_payment(comment: str, expected_ton: float) -> dict[str, Any] | None:
    """Ищет входящую транзакцию по комментарию и минимальной сумме."""
    if not ton_is_configured():
        return None

    expected_nano = int(float(expected_ton) * NANO)

    for tx in _load_recent_transactions():
        in_msg = tx.get("in_msg") or {}
        if not isinstance(in_msg, dict):
            continue

        value_raw = in_msg.get("value") or 0
        try:
            value_nano = int(value_raw)
        except (TypeError, ValueError):
            continue

        tx_comment = _decode_comment(in_msg)
        tx_hash = _tx_hash(tx)

        if is_ton_tx_used(tx_hash):
            continue

        if tx_comment == comment and value_nano >= expected_nano:
            return {
                "hash": tx_hash,
                "amount_ton": value_nano / NANO,
                "comment": tx_comment,
            }

    return None
