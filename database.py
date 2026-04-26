from __future__ import annotations

import csv
import os
import sqlite3
from datetime import datetime
from typing import Any

from config import settings
from currency_utils import normalize_currency, kzt_to_currency


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def db_connect() -> sqlite3.Connection:
    db_dir = os.path.dirname(settings.db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = db_connect()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            balance REAL DEFAULT 0,
            ref_by INTEGER,
            currency TEXT DEFAULT 'KZT',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            category TEXT NOT NULL,
            product TEXT NOT NULL,
            details TEXT,
            price REAL DEFAULT 0,
            currency TEXT DEFAULT 'KZT',
            display_amount REAL DEFAULT 0,
            payment_method TEXT DEFAULT 'manual',
            status TEXT DEFAULT 'new',
            reward_paid INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            reason TEXT NOT NULL,
            order_id INTEGER,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS refunds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount_kzt REAL NOT NULL,
            amount_ton REAL DEFAULT 0,
            method TEXT NOT NULL,
            status TEXT DEFAULT 'done',
            note TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY,
            amount REAL NOT NULL,
            max_uses INTEGER DEFAULT 1,
            used_count INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_usages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(code, user_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            message TEXT NOT NULL,
            admin_reply TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT NOT NULL,
            answered_at TEXT,
            closed_at TEXT,
            last_message_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            sender TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS product_items (
            sku TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            code TEXT NOT NULL,
            title TEXT NOT NULL,
            price REAL DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS no_comment_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            user_id INTEGER NOT NULL,
            username TEXT,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'new',
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    # Миграции для старых баз Railway: добавляем поля тикетов, если их ещё нет.
    cur.execute("PRAGMA table_info(support_tickets)")
    ticket_columns = {row[1] for row in cur.fetchall()}
    if "admin_reply" not in ticket_columns:
        cur.execute("ALTER TABLE support_tickets ADD COLUMN admin_reply TEXT")
    if "answered_at" not in ticket_columns:
        cur.execute("ALTER TABLE support_tickets ADD COLUMN answered_at TEXT")
    if "closed_at" not in ticket_columns:
        cur.execute("ALTER TABLE support_tickets ADD COLUMN closed_at TEXT")
    if "last_message_at" not in ticket_columns:
        cur.execute("ALTER TABLE support_tickets ADD COLUMN last_message_at TEXT")

    # Миграции мультивалютности.
    cur.execute("PRAGMA table_info(users)")
    user_columns = {row[1] for row in cur.fetchall()}
    if "currency" not in user_columns:
        cur.execute("ALTER TABLE users ADD COLUMN currency TEXT DEFAULT 'KZT'")

    cur.execute("PRAGMA table_info(orders)")
    order_columns = {row[1] for row in cur.fetchall()}
    if "currency" not in order_columns:
        cur.execute("ALTER TABLE orders ADD COLUMN currency TEXT DEFAULT 'KZT'")
    if "display_amount" not in order_columns:
        cur.execute("ALTER TABLE orders ADD COLUMN display_amount REAL DEFAULT 0")

    # Переносим старые тикеты в таблицу истории сообщений, если у тикета ещё нет истории.
    cur.execute("SELECT id, user_id, username, message, admin_reply, created_at, answered_at FROM support_tickets")
    for ticket in cur.fetchall():
        cur.execute("SELECT COUNT(*) FROM support_messages WHERE ticket_id=?", (ticket["id"],))
        if int(cur.fetchone()[0] or 0) == 0:
            if ticket["message"]:
                cur.execute(
                    """
                    INSERT INTO support_messages (ticket_id, sender, user_id, username, message, created_at)
                    VALUES (?, 'user', ?, ?, ?, ?)
                    """,
                    (ticket["id"], ticket["user_id"], ticket["username"] or "", ticket["message"], ticket["created_at"] or now()),
                )
            if ticket["admin_reply"]:
                cur.execute(
                    """
                    INSERT INTO support_messages (ticket_id, sender, user_id, username, message, created_at)
                    VALUES (?, 'admin', ?, 'admin', ?, ?)
                    """,
                    (ticket["id"], settings.admin_id or 0, ticket["admin_reply"], ticket["answered_at"] or now()),
                )
            cur.execute("UPDATE support_tickets SET last_message_at=COALESCE(last_message_at, ?) WHERE id=?", (now(), ticket["id"]))

    conn.commit()
    conn.close()
    ensure_ton_tables()
    seed_product_catalog()


def upsert_user(user_id: int, username: str | None, full_name: str | None, ref_by: int | None = None) -> bool:
    conn = db_connect()
    cur = conn.cursor()
    existing = get_user(user_id, conn=conn)
    was_new = False
    if existing:
        cur.execute(
            "UPDATE users SET username=?, full_name=?, updated_at=? WHERE user_id=?",
            (username or "", full_name or "", now(), user_id),
        )
    else:
        was_new = True
        safe_ref = ref_by if ref_by and ref_by != user_id else None
        cur.execute(
            """
            INSERT INTO users (user_id, username, full_name, balance, ref_by, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?, ?)
            """,
            (user_id, username or "", full_name or "", safe_ref, now(), now()),
        )
    conn.commit()
    conn.close()
    return was_new


def get_user(user_id: int, conn: sqlite3.Connection | None = None) -> sqlite3.Row | None:
    own = conn is None
    conn = conn or db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if own:
        conn.close()
    return row


def get_user_currency(user_id: int) -> str:
    user = get_user(user_id)
    if not user:
        return normalize_currency(settings.default_currency)
    try:
        return normalize_currency(user["currency"])
    except Exception:
        return normalize_currency(settings.default_currency)


def set_user_currency(user_id: int, currency: str) -> str:
    code = normalize_currency(currency)
    conn = db_connect()
    cur = conn.cursor()
    user = get_user(user_id, conn=conn)
    if not user:
        cur.execute(
            """
            INSERT INTO users (user_id, username, full_name, balance, ref_by, currency, created_at, updated_at)
            VALUES (?, '', '', 0, NULL, ?, ?, ?)
            """,
            (user_id, code, now(), now()),
        )
    else:
        cur.execute("UPDATE users SET currency=?, updated_at=? WHERE user_id=?", (code, now(), user_id))
    conn.commit()
    conn.close()
    return code


def get_users(limit: int = 10000) -> list[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows


def change_balance(user_id: int, amount: float, reason: str, order_id: int | None = None) -> float:
    conn = db_connect()
    cur = conn.cursor()
    user = get_user(user_id, conn=conn)
    if not user:
        cur.execute(
            """
            INSERT INTO users (user_id, username, full_name, balance, ref_by, created_at, updated_at)
            VALUES (?, '', '', 0, NULL, ?, ?)
            """,
            (user_id, now(), now()),
        )
        old_balance = 0.0
    else:
        old_balance = float(user["balance"] or 0)

    new_balance = round(old_balance + float(amount), 2)
    cur.execute("UPDATE users SET balance=?, updated_at=? WHERE user_id=?", (new_balance, now(), user_id))
    cur.execute(
        "INSERT INTO transactions (user_id, amount, reason, order_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, float(amount), reason, order_id, now()),
    )
    conn.commit()
    conn.close()
    return new_balance


def create_order(
    user_id: int,
    username: str | None,
    category: str,
    product: str,
    details: str,
    price: float = 0,
    payment_method: str = "manual",
    status: str = "new",
    currency: str = "KZT",
    display_amount: float | None = None,
) -> int:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO orders (user_id, username, category, product, details, price, currency, display_amount, payment_method, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            username or "",
            category,
            product,
            details,
            float(price),
            normalize_currency(currency),
            float(display_amount if display_amount is not None else kzt_to_currency(float(price), currency)),
            payment_method,
            status,
            now(),
            now(),
        ),
    )
    order_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return order_id


def get_order(order_id: int) -> sqlite3.Row | None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE id=?", (order_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_user_orders(user_id: int, limit: int = 5) -> list[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows


def list_orders(statuses: tuple[str, ...] = ("new", "paid"), limit: int = 10) -> list[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in statuses)
    cur.execute(f"SELECT * FROM orders WHERE status IN ({placeholders}) ORDER BY id DESC LIMIT ?", (*statuses, limit))
    rows = cur.fetchall()
    conn.close()
    return rows


def update_order_status(order_id: int, status: str) -> None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", (status, now(), order_id))
    conn.commit()
    conn.close()


def mark_reward_paid(order_id: int) -> None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET reward_paid=1, updated_at=? WHERE id=?", (now(), order_id))
    conn.commit()
    conn.close()


def get_refund_by_order(order_id: int) -> sqlite3.Row | None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM refunds WHERE order_id=? ORDER BY id DESC LIMIT 1", (order_id,))
    row = cur.fetchone()
    conn.close()
    return row


def create_refund_record(
    order_id: int,
    user_id: int,
    amount_kzt: float,
    amount_ton: float = 0,
    method: str = "balance",
    status: str = "done",
    note: str | None = None,
) -> int:
    existing = get_refund_by_order(order_id)
    if existing:
        return int(existing["id"])
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO refunds (order_id, user_id, amount_kzt, amount_ton, method, status, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (order_id, user_id, float(amount_kzt), float(amount_ton), method, status, note or "", now()),
    )
    refund_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return refund_id


def create_promocode(code: str, amount: float, max_uses: int) -> None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO promocodes (code, amount, max_uses, used_count, active, created_at)
        VALUES (?, ?, ?, COALESCE((SELECT used_count FROM promocodes WHERE code=?), 0), 1, ?)
        """,
        (code.upper(), float(amount), int(max_uses), code.upper(), now()),
    )
    conn.commit()
    conn.close()


def activate_promocode(code: str, user_id: int) -> tuple[bool, str, float]:
    code = code.strip().upper()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM promocodes WHERE code=?", (code,))
    promo = cur.fetchone()
    if not promo or int(promo["active"]) != 1:
        conn.close()
        return False, "Промокод не найден или выключен.", 0.0
    if int(promo["used_count"]) >= int(promo["max_uses"]):
        conn.close()
        return False, "Лимит активаций промокода уже закончился.", 0.0
    try:
        cur.execute("INSERT INTO promo_usages (code, user_id, created_at) VALUES (?, ?, ?)", (code, user_id, now()))
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Вы уже активировали этот промокод.", 0.0

    amount = float(promo["amount"])
    cur.execute("UPDATE promocodes SET used_count=used_count+1 WHERE code=?", (code,))
    cur.execute("UPDATE users SET balance=ROUND(balance + ?, 2), updated_at=? WHERE user_id=?", (amount, now(), user_id))
    cur.execute(
        "INSERT INTO transactions (user_id, amount, reason, order_id, created_at) VALUES (?, ?, ?, NULL, ?)",
        (user_id, amount, f"Промокод {code}", now()),
    )
    conn.commit()
    conn.close()
    return True, f"Промокод активирован. На баланс начислено {amount:g}.", amount


def create_support_ticket(user_id: int, username: str | None, message: str) -> int:
    conn = db_connect()
    cur = conn.cursor()
    created = now()
    cur.execute(
        """
        INSERT INTO support_tickets (user_id, username, message, status, created_at, last_message_at)
        VALUES (?, ?, ?, 'open', ?, ?)
        """,
        (user_id, username or "", message, created, created),
    )
    ticket_id = int(cur.lastrowid)
    cur.execute(
        """
        INSERT INTO support_messages (ticket_id, sender, user_id, username, message, created_at)
        VALUES (?, 'user', ?, ?, ?, ?)
        """,
        (ticket_id, user_id, username or "", message, created),
    )
    conn.commit()
    conn.close()
    return ticket_id


def get_support_ticket(ticket_id: int) -> sqlite3.Row | None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM support_tickets WHERE id=?", (ticket_id,))
    ticket = cur.fetchone()
    conn.close()
    return ticket


def list_user_support_tickets(user_id: int, limit: int = 10) -> list[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM support_tickets
        WHERE user_id=?
        ORDER BY COALESCE(last_message_at, created_at) DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def list_active_support_tickets(limit: int = 20) -> list[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM support_tickets
        WHERE status != 'closed'
        ORDER BY COALESCE(last_message_at, created_at) DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_ticket_messages(ticket_id: int, limit: int = 20) -> list[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM support_messages
        WHERE ticket_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (ticket_id, limit),
    )
    rows = list(reversed(cur.fetchall()))
    conn.close()
    return rows


def add_support_message(
    ticket_id: int,
    sender: str,
    user_id: int,
    username: str | None,
    message: str,
) -> sqlite3.Row | None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM support_tickets WHERE id=?", (ticket_id,))
    ticket = cur.fetchone()
    if not ticket:
        conn.close()
        return None
    if ticket["status"] == "closed":
        conn.close()
        return None

    created = now()
    cur.execute(
        """
        INSERT INTO support_messages (ticket_id, sender, user_id, username, message, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (ticket_id, sender, user_id, username or "", message, created),
    )

    if sender == "admin":
        cur.execute(
            """
            UPDATE support_tickets
            SET admin_reply=?, status='answered', answered_at=?, last_message_at=?
            WHERE id=?
            """,
            (message, created, created, ticket_id),
        )
    else:
        cur.execute(
            """
            UPDATE support_tickets
            SET message=?, status='open', last_message_at=?
            WHERE id=?
            """,
            (message, created, ticket_id),
        )

    conn.commit()
    cur.execute("SELECT * FROM support_tickets WHERE id=?", (ticket_id,))
    updated = cur.fetchone()
    conn.close()
    return updated


def answer_support_ticket(ticket_id: int, reply_text: str) -> sqlite3.Row | None:
    return add_support_message(ticket_id, "admin", settings.admin_id or 0, "admin", reply_text)


def count_user_support_tickets(user_id: int) -> dict[str, int]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM support_tickets WHERE user_id=?", (user_id,))
    total = int(cur.fetchone()[0] or 0)
    cur.execute("SELECT COUNT(*) FROM support_tickets WHERE user_id=? AND status!='closed'", (user_id,))
    open_count = int(cur.fetchone()[0] or 0)
    conn.close()
    return {"total": total, "open": open_count}


def close_support_ticket(ticket_id: int) -> bool:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE support_tickets SET status='closed', closed_at=?, last_message_at=? WHERE id=?", (now(), now(), ticket_id))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def get_stats() -> dict[str, Any]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    users_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM orders")
    orders_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM orders WHERE status IN ('new','paid','work')")
    active_orders = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(price), 0) FROM orders WHERE status='done'")
    done_sum = float(cur.fetchone()[0] or 0)
    cur.execute("SELECT COUNT(*) FROM support_tickets WHERE status='open'")
    open_tickets = cur.fetchone()[0]
    conn.close()
    return {
        "users_count": users_count,
        "orders_count": orders_count,
        "active_orders": active_orders,
        "done_sum": done_sum,
        "open_tickets": open_tickets,
    }


def top_clients(limit: int = 10) -> list[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT users.user_id, users.username, users.full_name,
               COUNT(orders.id) AS orders_count,
               COALESCE(SUM(orders.price), 0) AS total_spent
        FROM users
        LEFT JOIN orders ON users.user_id = orders.user_id AND orders.status='done'
        GROUP BY users.user_id
        HAVING orders_count > 0
        ORDER BY total_spent DESC, orders_count DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_user_activity_stats(user_id: int) -> dict[str, Any]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            COUNT(*) AS orders_count,
            SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done_orders,
            SUM(CASE WHEN status='done' AND category!='top_up' THEN price ELSE 0 END) AS total_spent
        FROM orders
        WHERE user_id=?
        """,
        (user_id,),
    )
    order_row = cur.fetchone()
    cur.execute("SELECT COUNT(*) AS refs_count FROM users WHERE ref_by=?", (user_id,))
    ref_row = cur.fetchone()
    conn.close()
    return {
        "orders_count": int(order_row["orders_count"] or 0),
        "done_orders": int(order_row["done_orders"] or 0),
        "total_spent": float(order_row["total_spent"] or 0),
        "refs_count": int(ref_row["refs_count"] or 0),
    }

# =========================
# PRODUCTS / ADMIN EXTRA
# =========================

def seed_product_catalog() -> None:
    from products import CUSTOM_PRODUCTS, PREMIUM_PACKAGES, PUBG_PACKAGES, STARS_PACKAGES, TOP_UP_AMOUNTS

    conn = db_connect()
    cur = conn.cursor()
    items: list[tuple[str, str, str, str, float]] = []
    for code, price in STARS_PACKAGES.items():
        items.append((f"stars:{code}", "stars", str(code), f"⭐ {code} Stars", float(price)))
    for code, price in PREMIUM_PACKAGES.items():
        items.append((f"premium:{code}", "premium", str(code), f"👑 Premium {code} мес.", float(price)))
    for code, price in PUBG_PACKAGES.items():
        items.append((f"pubg:{code}", "pubg", str(code), f"🎮 PUBG {code} UC", float(price)))
    for amount in TOP_UP_AMOUNTS:
        items.append((f"topup:{amount}", "topup", str(amount), f"💰 Пополнение {amount:g}", float(amount)))
    for key, item in CUSTOM_PRODUCTS.items():
        items.append((f"custom:{key}", "custom", key, str(item["title"]), 0.0))

    for sku, kind, code, title, price in items:
        cur.execute("SELECT 1 FROM product_items WHERE sku=?", (sku,))
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO product_items (sku, kind, code, title, price, enabled, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                (sku, kind, code, title, price, now()),
            )
    conn.commit()
    conn.close()


def get_product_item(sku: str) -> sqlite3.Row | None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM product_items WHERE sku=?", (sku,))
    row = cur.fetchone()
    conn.close()
    return row


def list_product_items(kind: str | None = None, include_disabled: bool = True) -> list[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    if kind:
        if include_disabled:
            cur.execute("SELECT * FROM product_items WHERE kind=? ORDER BY kind, CAST(code AS INTEGER), code", (kind,))
        else:
            cur.execute("SELECT * FROM product_items WHERE kind=? AND enabled=1 ORDER BY kind, CAST(code AS INTEGER), code", (kind,))
    else:
        cur.execute("SELECT * FROM product_items ORDER BY kind, CAST(code AS INTEGER), code")
    rows = cur.fetchall()
    conn.close()
    return rows


def get_product_price(kind: str, code: str, default: float = 0.0) -> float:
    row = get_product_item(f"{kind}:{code}")
    if row:
        return float(row["price"] or 0)
    return float(default)


def is_product_enabled(sku: str) -> bool:
    row = get_product_item(sku)
    if not row:
        return True
    return int(row["enabled"] or 0) == 1


def set_product_price(sku: str, price: float) -> bool:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE product_items SET price=?, updated_at=? WHERE sku=?", (float(price), now(), sku))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def toggle_product_enabled(sku: str) -> bool | None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT enabled FROM product_items WHERE sku=?", (sku,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    new_value = 0 if int(row["enabled"] or 0) == 1 else 1
    cur.execute("UPDATE product_items SET enabled=?, updated_at=? WHERE sku=?", (new_value, now(), sku))
    conn.commit()
    conn.close()
    return bool(new_value)


def create_no_comment_report(order_id: int | None, user_id: int, username: str | None, message: str) -> int:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO no_comment_reports (order_id, user_id, username, message, status, created_at) VALUES (?, ?, ?, ?, 'new', ?)",
        (order_id, user_id, username or "", message, now()),
    )
    report_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return report_id


def create_review(order_id: int, user_id: int, rating: int, comment: str | None = None) -> tuple[bool, str]:
    conn = db_connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO reviews (order_id, user_id, rating, comment, created_at) VALUES (?, ?, ?, ?, ?)",
            (order_id, user_id, int(rating), comment or "", now()),
        )
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Вы уже оставили отзыв по этому заказу."
    conn.commit()
    conn.close()
    return True, "Спасибо за отзыв!"


def get_admin_stats_expanded() -> dict[str, Any]:
    conn = db_connect()
    cur = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")

    def one(query: str, params: tuple[Any, ...] = ()) -> Any:
        cur.execute(query, params)
        return cur.fetchone()[0]

    data = {
        "users_count": int(one("SELECT COUNT(*) FROM users") or 0),
        "new_users_today": int(one("SELECT COUNT(*) FROM users WHERE substr(created_at,1,10)=?", (today,)) or 0),
        "orders_count": int(one("SELECT COUNT(*) FROM orders") or 0),
        "orders_today": int(one("SELECT COUNT(*) FROM orders WHERE substr(created_at,1,10)=?", (today,)) or 0),
        "paid_today": float(one("SELECT COALESCE(SUM(price),0) FROM orders WHERE status IN ('paid','work','done') AND substr(updated_at,1,10)=?", (today,)) or 0),
        "paid_month": float(one("SELECT COALESCE(SUM(price),0) FROM orders WHERE status IN ('paid','work','done') AND substr(updated_at,1,7)=?", (month,)) or 0),
        "done_orders": int(one("SELECT COUNT(*) FROM orders WHERE status='done'") or 0),
        "cancelled_orders": int(one("SELECT COUNT(*) FROM orders WHERE status='cancelled'") or 0),
        "waiting_ton": int(one("SELECT COUNT(*) FROM orders WHERE status='waiting_ton'") or 0),
        "active_orders": int(one("SELECT COUNT(*) FROM orders WHERE status IN ('new','paid','work','waiting_ton')") or 0),
        "open_tickets": int(one("SELECT COUNT(*) FROM support_tickets WHERE status!='closed'") or 0),
        "reviews_count": int(one("SELECT COUNT(*) FROM reviews") or 0),
        "avg_rating": float(one("SELECT COALESCE(AVG(rating),0) FROM reviews") or 0),
    }
    conn.close()
    return data


def export_table_to_csv(table: str, filepath: str) -> None:
    allowed = {"users", "orders", "transactions", "refunds", "support_tickets", "support_messages", "ton_invoices", "reviews", "no_comment_reports"}
    if table not in allowed:
        raise ValueError("Недоступная таблица для экспорта")
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {table}")
    rows = cur.fetchall()
    fieldnames = [desc[0] for desc in cur.description]
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        for row in rows:
            writer.writerow([row[name] for name in fieldnames])
    conn.close()


# =========================
# TON INVOICES
# =========================

def ensure_ton_tables() -> None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ton_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount_kzt REAL NOT NULL,
            amount_ton REAL NOT NULL,
            comment TEXT NOT NULL UNIQUE,
            status TEXT DEFAULT 'pending',
            tx_hash TEXT,
            created_at TEXT NOT NULL,
            paid_at TEXT,
            expires_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ton_used_transactions (
            tx_hash TEXT PRIMARY KEY,
            order_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount_ton REAL NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute("PRAGMA table_info(ton_invoices)")
    ton_columns = {row[1] for row in cur.fetchall()}
    if "expires_at" not in ton_columns:
        cur.execute("ALTER TABLE ton_invoices ADD COLUMN expires_at TEXT")
    conn.commit()
    conn.close()


def create_ton_invoice(order_id: int, user_id: int, amount_kzt: float, amount_ton: float, comment: str, expires_at: str | None = None) -> int:
    ensure_ton_tables()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO ton_invoices (order_id, user_id, amount_kzt, amount_ton, comment, status, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (order_id, user_id, float(amount_kzt), float(amount_ton), comment, now(), expires_at),
    )
    invoice_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return invoice_id


def get_ton_invoice_by_order(order_id: int):
    ensure_ton_tables()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM ton_invoices WHERE order_id=? ORDER BY id DESC LIMIT 1", (order_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_ton_invoice_by_comment(comment: str):
    ensure_ton_tables()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM ton_invoices WHERE comment=?", (comment,))
    row = cur.fetchone()
    conn.close()
    return row


def list_pending_ton_invoices(limit: int = 100):
    ensure_ton_tables()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM ton_invoices WHERE status='pending' ORDER BY created_at ASC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows


def is_ton_tx_used(tx_hash: str) -> bool:
    ensure_ton_tables()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM ton_used_transactions WHERE tx_hash=?", (tx_hash,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def mark_ton_invoice_paid(order_id: int, tx_hash: str, amount_ton: float) -> None:
    ensure_ton_tables()
    invoice = get_ton_invoice_by_order(order_id)
    if not invoice:
        return
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE ton_invoices SET status='paid', tx_hash=?, paid_at=? WHERE order_id=?",
        (tx_hash, now(), order_id),
    )
    cur.execute(
        "INSERT OR IGNORE INTO ton_used_transactions (tx_hash, order_id, user_id, amount_ton, created_at) VALUES (?, ?, ?, ?, ?)",
        (tx_hash, order_id, int(invoice['user_id']), float(amount_ton), now()),
    )
    conn.commit()
    conn.close()


def expire_ton_invoice(order_id: int) -> None:
    ensure_ton_tables()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE ton_invoices SET status='expired' WHERE order_id=? AND status='pending'", (order_id,))
    conn.commit()
    conn.close()
