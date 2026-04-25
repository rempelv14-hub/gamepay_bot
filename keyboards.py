from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from products import PREMIUM_PACKAGES, PUBG_PACKAGES, STARS_PACKAGES, TOP_UP_AMOUNTS
from config import settings


def money(value: float | int) -> str:
    if float(value).is_integer():
        return f"{int(value)}{settings.currency_symbol}"
    return f"{float(value):.2f}{settings.currency_symbol}"


def bottom_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📋 Меню"), KeyboardButton(text="👤 Профиль")]],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐ Купить звёзды", callback_data="buy_stars"),
                InlineKeyboardButton(text="💳 Продать звёзды", callback_data="custom:sell_stars"),
            ],
            [
                InlineKeyboardButton(text="⏰ Аренда NFT", callback_data="custom:rent_nft"),
                InlineKeyboardButton(text="🎁 Купить NFT", callback_data="custom:buy_nft"),
            ],
            [InlineKeyboardButton(text="🧸 Купить обычный подарок", callback_data="custom:buy_gift")],
            [InlineKeyboardButton(text="💎 Купить TON", callback_data="custom:buy_ton")],
            [InlineKeyboardButton(text="👑 Премиум", callback_data="premium")],
            [InlineKeyboardButton(text="🎮 PUBG UC", callback_data="pubg")],
            [
                InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="top_up_balance"),
                InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
            ],
            [
                InlineKeyboardButton(text="📞 Поддержка", callback_data="support"),
                InlineKeyboardButton(text="🧮 Калькулятор", callback_data="calculator"),
            ],
            [
                InlineKeyboardButton(text="🎟 Промокод", callback_data="promo"),
                InlineKeyboardButton(text="ℹ️ Информация", callback_data="info"),
            ],
            [InlineKeyboardButton(text="🏆 Топ клиентов", callback_data="top_clients")],
            [InlineKeyboardButton(text="🤝 Стать партнёром", callback_data="partner")],
        ]
    )


def back_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")]])


def support_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Создать тикет", callback_data="support_create")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="back_menu")],
        ]
    )


def admin_ticket_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Закрыть тикет", callback_data=f"admin_ticket_close:{ticket_id}")],
        ]
    )


def stars_packages_kb() -> InlineKeyboardMarkup:
    rows = []
    items = list(STARS_PACKAGES.items())
    for i in range(0, len(items), 2):
        row = []
        for amount, price in items[i:i + 2]:
            row.append(InlineKeyboardButton(text=f"⭐ {amount} Stars — {money(price)}", callback_data=f"fixed:stars:{amount}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def premium_kb() -> InlineKeyboardMarkup:
    rows = []
    items = list(PREMIUM_PACKAGES.items())
    for i in range(0, len(items), 2):
        row = []
        for months, price in items[i:i + 2]:
            row.append(InlineKeyboardButton(text=f"👑 {months} мес. — {money(price)}", callback_data=f"fixed:premium:{months}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pubg_packages_kb() -> InlineKeyboardMarkup:
    rows = []
    items = list(PUBG_PACKAGES.items())
    for i in range(0, len(items), 2):
        row = []
        for uc, price in items[i:i + 2]:
            row.append(InlineKeyboardButton(text=f"🎮 {uc} UC — {money(price)}", callback_data=f"pubg_pack:{uc}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def top_up_kb() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(TOP_UP_AMOUNTS), 2):
        rows.append([
            InlineKeyboardButton(text=money(amount), callback_data=f"topup_amount:{amount}")
            for amount in TOP_UP_AMOUNTS[i:i + 2]
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
            [InlineKeyboardButton(text="⬅️ Меню", callback_data="back_menu")],
        ]
    )


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders")],
            [InlineKeyboardButton(text="🎟 Активировать промокод", callback_data="promo")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")],
        ]
    )


def admin_order_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟡 В работу", callback_data=f"admin_work:{order_id}"),
                InlineKeyboardButton(text="✅ Выполнено", callback_data=f"admin_done:{order_id}"),
            ],
            [InlineKeyboardButton(text="❌ Отменить", callback_data=f"admin_cancel:{order_id}")],
        ]
    )


def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📦 Новые заказы", callback_data="admin_orders"),
                InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
            ],
            [
                InlineKeyboardButton(text="🎟 Создать промокод", callback_data="admin_create_promo"),
                InlineKeyboardButton(text="📣 Рассылка", callback_data="admin_broadcast"),
            ],
            [InlineKeyboardButton(text="⬅️ Меню клиента", callback_data="back_menu")],
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
