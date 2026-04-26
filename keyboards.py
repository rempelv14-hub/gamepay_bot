from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from config import settings
from products import CUSTOM_PRODUCTS, PREMIUM_PACKAGES, PUBG_PACKAGES, STARS_PACKAGES, TOP_UP_AMOUNTS


def money(value: float | int) -> str:
    try:
        if float(value).is_integer():
            return f"{int(value)}{settings.currency_symbol}"
        return f"{float(value):.2f}{settings.currency_symbol}"
    except Exception:
        return f"{value}{settings.currency_symbol}"


def _items(kind: str, fallback: dict[str, float | int]):
    try:
        from database import list_product_items
        rows = list_product_items(kind, include_disabled=False)
        if rows:
            return [(str(row["code"]), float(row["price"] or 0), str(row["title"])) for row in rows]
    except Exception:
        pass
    return [(str(code), float(price), "") for code, price in fallback.items()]


def _enabled(sku: str) -> bool:
    try:
        from database import is_product_enabled
        return is_product_enabled(sku)
    except Exception:
        return True


def bottom_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Меню"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="📦 Мои заказы"), KeyboardButton(text="📞 Поддержка")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def main_menu_kb() -> InlineKeyboardMarkup:
    rows = []
    row1 = []
    if _enabled("stars:50"):
        row1.append(InlineKeyboardButton(text="⭐ Купить звёзды", callback_data="buy_stars"))
    if _enabled("custom:sell_stars"):
        row1.append(InlineKeyboardButton(text="💳 Продать звёзды", callback_data="custom:sell_stars"))
    if row1:
        rows.append(row1)

    row2 = []
    if _enabled("custom:rent_nft"):
        row2.append(InlineKeyboardButton(text="⏰ Аренда NFT", callback_data="custom:rent_nft"))
    if _enabled("custom:buy_nft"):
        row2.append(InlineKeyboardButton(text="🎁 Купить NFT", callback_data="custom:buy_nft"))
    if row2:
        rows.append(row2)

    if _enabled("custom:buy_gift"):
        rows.append([InlineKeyboardButton(text="🧸 Купить обычный подарок", callback_data="custom:buy_gift")])
    if _enabled("custom:buy_ton"):
        rows.append([InlineKeyboardButton(text="💎 Купить TON", callback_data="custom:buy_ton")])
    if _enabled("premium:3"):
        rows.append([InlineKeyboardButton(text="👑 Премиум", callback_data="premium")])
    if _enabled("pubg:60"):
        rows.append([InlineKeyboardButton(text="🎮 PUBG UC", callback_data="pubg")])
    rows.extend([
        [
            InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="top_up_balance"),
            InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
        ],
        [
            InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders"),
            InlineKeyboardButton(text="📞 Поддержка", callback_data="support"),
        ],
        [
            InlineKeyboardButton(text="🧮 Калькулятор", callback_data="calculator"),
            InlineKeyboardButton(text="❓ FAQ", callback_data="faq"),
        ],
        [InlineKeyboardButton(text="ℹ️ Информация", callback_data="info")],
        [InlineKeyboardButton(text="🏆 Топ клиентов", callback_data="top_clients")],
        [InlineKeyboardButton(text="🤝 Стать партнёром", callback_data="partner")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")]])


def support_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Создать тикет", callback_data="support_create")],
            [InlineKeyboardButton(text="📋 Мои тикеты", callback_data="support_my_tickets")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="back_menu")],
        ]
    )


def user_ticket_kb(ticket_id: int, is_closed: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if not is_closed:
        rows.append([InlineKeyboardButton(text="✍️ Ответить в тикет", callback_data=f"support_ticket_reply:{ticket_id}")])
        rows.append([InlineKeyboardButton(text="✅ Закрыть тикет", callback_data=f"support_ticket_close:{ticket_id}")])
    rows.append([InlineKeyboardButton(text="📋 Мои тикеты", callback_data="support_my_tickets")])
    rows.append([InlineKeyboardButton(text="⬅️ В поддержку", callback_data="support")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_ticket_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📜 История тикета", callback_data=f"admin_ticket_history:{ticket_id}")],
            [InlineKeyboardButton(text="✉️ Ответить на тикет", callback_data=f"admin_ticket_reply:{ticket_id}")],
            [InlineKeyboardButton(text="✅ Закрыть тикет", callback_data=f"admin_ticket_close:{ticket_id}")],
        ]
    )


def stars_packages_kb() -> InlineKeyboardMarkup:
    rows = []
    items = _items("stars", STARS_PACKAGES)
    for i in range(0, len(items), 2):
        row = []
        for amount, price, _title in items[i:i + 2]:
            row.append(InlineKeyboardButton(text=f"⭐ {amount} Stars — {money(price)}", callback_data=f"fixed:stars:{amount}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def premium_kb() -> InlineKeyboardMarkup:
    rows = []
    items = _items("premium", PREMIUM_PACKAGES)
    for i in range(0, len(items), 2):
        row = []
        for months, price, _title in items[i:i + 2]:
            row.append(InlineKeyboardButton(text=f"👑 {months} мес. — {money(price)}", callback_data=f"fixed:premium:{months}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pubg_packages_kb() -> InlineKeyboardMarkup:
    rows = []
    items = _items("pubg", PUBG_PACKAGES)
    for i in range(0, len(items), 2):
        row = []
        for uc, price, _title in items[i:i + 2]:
            row.append(InlineKeyboardButton(text=f"🎮 {uc} UC — {money(price)}", callback_data=f"pubg_pack:{uc}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def top_up_kb() -> InlineKeyboardMarkup:
    rows = []
    items = _items("topup", {str(x): x for x in TOP_UP_AMOUNTS})
    amounts = [(code, price) for code, price, _title in items]
    for i in range(0, len(amounts), 2):
        rows.append([
            InlineKeyboardButton(text=money(price), callback_data=f"topup_amount:{price:g}")
            for code, price in amounts[i:i + 2]
        ])
    rows.append([InlineKeyboardButton(text="✍️ Другая сумма", callback_data="topup_custom")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_choice_kb(price: float) -> InlineKeyboardMarkup:
    buttons = []
    if price > 0:
        buttons.append([InlineKeyboardButton(text="💎 Оплатить TON автоматически", callback_data="pay:ton")])
        buttons.append([InlineKeyboardButton(text="💰 Оплатить с баланса", callback_data="pay:balance")])
    buttons.append([InlineKeyboardButton(text="🧾 Создать заявку / оплата вручную", callback_data="pay:manual")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def ton_invoice_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔎 Проверить TON оплату", callback_data=f"ton_check:{order_id}")],
            [InlineKeyboardButton(text="⚠️ Оплатил без комментария", callback_data=f"ton_no_comment:{order_id}")],
            [InlineKeyboardButton(text="⬅️ Меню", callback_data="back_menu")],
        ]
    )


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")],
        ]
    )


def user_orders_kb(orders) -> InlineKeyboardMarkup:
    rows = []
    for order in orders:
        status_icons = {
            "new": "🧾",
            "waiting_ton": "💎",
            "paid": "💰",
            "work": "🟡",
            "done": "✅",
            "cancelled": "❌",
        }
        icon = status_icons.get(order["status"], "📦")
        title = str(order["product"])
        if len(title) > 26:
            title = title[:23] + "..."
        rows.append([
            InlineKeyboardButton(text=f"{icon} #{order['id']} — {title}", callback_data=f"user_order:{order['id']}")
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_order_kb(order_id: int, status: str) -> InlineKeyboardMarkup:
    rows = []
    if status == "waiting_ton":
        rows.append([InlineKeyboardButton(text="🔎 Проверить TON оплату", callback_data=f"ton_check:{order_id}")])
        rows.append([InlineKeyboardButton(text="⚠️ Оплатил без комментария", callback_data=f"ton_no_comment:{order_id}")])
    rows.append([InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders")])
    rows.append([InlineKeyboardButton(text="📞 Поддержка", callback_data="support")])
    rows.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_order_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟡 В работу", callback_data=f"admin_work:{order_id}"),
                InlineKeyboardButton(text="✅ Выполнено", callback_data=f"admin_done:{order_id}"),
            ],
            [InlineKeyboardButton(text="✉️ Написать клиенту", callback_data=f"admin_order_msg:{order_id}")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data=f"admin_cancel:{order_id}")],
        ]
    )


def review_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{i}⭐", callback_data=f"review:{order_id}:{i}") for i in range(1, 6)],
            [InlineKeyboardButton(text="Не оценивать", callback_data=f"review_skip:{order_id}")],
        ]
    )


def admin_panel_kb(role: str = "owner") -> InlineKeyboardMarkup:
    rows = []
    if role in {"owner", "manager"}:
        rows.append([
            InlineKeyboardButton(text="📦 Новые заказы", callback_data="admin_orders"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
        ])
    if role == "owner":
        rows.append([
            InlineKeyboardButton(text="⚙️ Товары/цены", callback_data="admin_products"),
            InlineKeyboardButton(text="📣 Рассылка", callback_data="admin_broadcast"),
        ])
        rows.append([
            InlineKeyboardButton(text="📁 Экспорт", callback_data="admin_export"),
            InlineKeyboardButton(text="💾 Бэкап базы", callback_data="admin_backup"),
        ])
    if role in {"owner", "manager", "support"}:
        rows.append([InlineKeyboardButton(text="🆘 Активные тикеты", callback_data="admin_tickets")])
    rows.append([InlineKeyboardButton(text="⬅️ Меню клиента", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_products_kb(items) -> InlineKeyboardMarkup:
    rows = []
    for item in items:
        icon = "✅" if int(item["enabled"] or 0) == 1 else "⛔"
        price = float(item["price"] or 0)
        price_text = money(price) if price > 0 else "договорная"
        title = str(item["title"])
        if len(title) > 25:
            title = title[:22] + "..."
        rows.append([InlineKeyboardButton(text=f"{icon} {title} — {price_text}", callback_data=f"admin_product:{item['sku']}")])
    rows.append([InlineKeyboardButton(text="⬅️ В админку", callback_data="admin_stats")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_product_kb(sku: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💵 Изменить цену", callback_data=f"admin_product_price:{sku}")],
            [InlineKeyboardButton(text="🔁 Включить/выключить", callback_data=f"admin_product_toggle:{sku}")],
            [InlineKeyboardButton(text="⬅️ К товарам", callback_data="admin_products")],
        ]
    )


def calculator_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐ Stars", callback_data="calc:stars"),
                InlineKeyboardButton(text="🎮 PUBG UC", callback_data="calc:uc"),
            ],
            [InlineKeyboardButton(text="👑 Premium", callback_data="calc:premium")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")],
        ]
    )


def calculator_result_kb(kind: str) -> InlineKeyboardMarkup:
    if kind == "stars":
        buy_button = InlineKeyboardButton(text="⭐ Оформить Stars", callback_data="buy_stars")
    elif kind == "uc":
        buy_button = InlineKeyboardButton(text="🎮 Оформить PUBG UC", callback_data="pubg")
    else:
        buy_button = InlineKeyboardButton(text="👑 Оформить Premium", callback_data="premium")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [buy_button],
            [InlineKeyboardButton(text="🧮 Новый расчёт", callback_data="calculator")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")],
        ]
    )
