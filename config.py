from __future__ import annotations

import asyncio
import html
import logging
import os
import tempfile
from datetime import datetime, timedelta
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import settings
from database import (
    change_balance,
    create_order,
    create_no_comment_report,
    create_review,
    create_refund_record,
    get_refund_by_order,
    create_support_ticket,
    count_user_support_tickets,
    close_support_ticket,
    get_support_ticket,
    get_ticket_messages,
    add_support_message,
    list_user_support_tickets,
    list_active_support_tickets,
    answer_support_ticket,
    get_order,
    export_table_to_csv,
    expire_ton_invoice,
    get_admin_stats_expanded,
    get_stats,
    get_product_item,
    get_product_price,
    get_user,
    get_user_currency,
    get_user_orders,
    get_user_activity_stats,
    get_users,
    init_db,
    is_product_enabled,
    list_orders,
    list_product_items,
    mark_reward_paid,
    top_clients,
    create_ton_invoice,
    get_ton_invoice_by_order,
    list_pending_ton_invoices,
    mark_ton_invoice_paid,
    set_product_price,
    set_user_currency,
    toggle_product_enabled,
    update_order_status,
    upsert_user,
)
from keyboards import (
    admin_order_kb,
    admin_panel_kb,
    admin_product_kb,
    admin_products_kb,
    calculator_choice_kb,
    calculator_result_kb,
    currency_choice_kb,
    back_menu_kb,
    bottom_menu_kb,
    main_menu_kb,
    money,
    payment_choice_kb,
    premium_kb,
    profile_kb,
    review_kb,
    pubg_packages_kb,
    stars_packages_kb,
    support_panel_kb,
    user_ticket_kb,
    admin_ticket_kb,
    top_up_kb,
    money_multi,
    ton_invoice_kb,
    user_orders_kb,
    user_order_kb,
)
from products import CUSTOM_PRODUCTS, PREMIUM_PACKAGES, PUBG_PACKAGES, STARS_PACKAGES
from states import AdminBroadcastFSM, AdminProductFSM, AdminTicketFSM, AdminOrderFSM, CalculatorFSM, NoCommentFSM, OrderFSM, PubgFSM, SupportFSM, TopUpFSM
from texts import INFO_TEXT, MENU_TEXT
from currency_utils import format_money, format_money_multi, kzt_to_currency, normalize_currency, parse_amount, payment_details_for
from ton_payments import find_ton_payment, get_ton_rate_kzt, kzt_to_ton, ton_invoice_comment, ton_is_configured

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("shop_bot")

router = Router()


# =========================
# HELPERS
# =========================


def admin_role(user_id: int) -> str:
    if user_id in settings.owner_ids:
        return "owner"
    if user_id in settings.manager_ids:
        return "manager"
    if user_id in settings.support_ids:
        return "support"
    if user_id in settings.admin_ids:
        return "owner"
    return "user"


def is_admin(user_id: int) -> bool:
    return admin_role(user_id) != "user"


def is_owner(user_id: int) -> bool:
    return admin_role(user_id) == "owner"


def can_manage_orders(user_id: int) -> bool:
    return admin_role(user_id) in {"owner", "manager"}


def can_manage_support(user_id: int) -> bool:
    return admin_role(user_id) in {"owner", "manager", "support"}


def can_manage_settings(user_id: int) -> bool:
    return admin_role(user_id) == "owner"


def admin_role_ru(user_id: int) -> str:
    return {
        "owner": "Владелец",
        "manager": "Менеджер",
        "support": "Поддержка",
        "user": "Нет доступа",
    }.get(admin_role(user_id), "Нет доступа")


def admin_ids() -> tuple[int, ...]:
    return settings.admin_ids


async def notify_admins(bot: Bot, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    for admin_id in admin_ids():
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
            await asyncio.sleep(0.03)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cannot notify admin %s: %s", admin_id, exc)


def safe(text: Any) -> str:
    return html.escape(str(text or ""))


def order_status_ru(status: str) -> str:
    return {
        "new": "новый / ждёт ручной оплаты",
        "paid": "оплачен",
        "waiting_ton": "ожидает TON оплату",
        "work": "в работе",
        "done": "выполнен",
        "cancelled": "отменён",
        "expired": "счёт истёк",
        "refund_balance": "возврат на баланс",
    }.get(status, status)


def ticket_status_ru(status: str) -> str:
    return {
        "open": "открыт",
        "answered": "ответ поддержки",
        "closed": "закрыт",
    }.get(status, status)


def user_mention(username: str | None, user_id: int) -> str:
    return f"@{safe(username)}" if username else f"ID <code>{user_id}</code>"


def estimate_package_price(packages: dict[str, float | int], amount: int) -> tuple[float, str]:
    normalized = {int(k): float(v) for k, v in packages.items()}
    if amount in normalized:
        return normalized[amount], "точная цена по готовому пакету"
    closest = min(normalized.keys(), key=lambda pack: abs(pack - amount))
    price = round((normalized[closest] / closest) * amount, 2)
    note = f"примерный расчёт по цене ближайшего пакета {closest}"
    return price, note


def current_package_prices(kind: str, fallback: dict[str, float | int]) -> dict[str, float]:
    rows = list_product_items(kind, include_disabled=False)
    if rows:
        return {str(row["code"]): float(row["price"] or 0) for row in rows}
    return {str(k): float(v) for k, v in fallback.items()}


def user_currency(user_id: int) -> str:
    return get_user_currency(user_id)


def money_for_user(amount_kzt: float | int, user_id: int) -> str:
    currency = user_currency(user_id)
    main = format_money(float(amount_kzt), currency)
    other = format_money(float(amount_kzt), "RUB" if currency == "KZT" else "KZT")
    return f"{main} / {other}"


def order_currency(order: dict[str, Any] | Any) -> str:
    try:
        return normalize_currency(order["currency"])
    except Exception:
        return "KZT"


def order_amount_text(order: dict[str, Any] | Any) -> str:
    price = float(order["price"] or 0)
    cur = order_currency(order)
    return f"{format_money(price, cur)} / {format_money(price, 'KZT' if cur == 'RUB' else 'RUB')}"


def manual_payment_title(payment_method: str) -> str:
    if payment_method == "manual_rub":
        return "ручная оплата ₽"
    if payment_method == "manual_kzt":
        return "ручная оплата ₸"
    return payment_method


def format_order_for_admin(order: dict[str, Any] | Any) -> str:
    username = order["username"] or "без username"
    return (
        f"<b>📦 Заказ #{order['id']}</b>\n\n"
        f"👤 Клиент: {user_mention(username if username != 'без username' else None, int(order['user_id']))}\n"
        f"🆔 User ID: <code>{order['user_id']}</code>\n\n"
        f"📂 Категория: <b>{safe(order['category'])}</b>\n"
        f"📦 Товар: <b>{safe(order['product'])}</b>\n"
        f"💵 Цена/сумма: <b>{order_amount_text(order)}</b>\n"
        f"💳 Оплата: <b>{safe(manual_payment_title(str(order['payment_method'])))}</b>\n"
        f"📝 Детали: {safe(order['details'])}\n\n"
        f"📌 Статус: <b>{order_status_ru(order['status'])}</b>\n"
        f"🕒 Создан: <code>{order['created_at']}</code>"
    )


def format_order_for_user(order: dict[str, Any] | Any) -> str:
    return (
        f"<b>Заказ #{order['id']}</b>\n"
        f"Товар: {safe(order['product'])}\n"
        f"Цена/сумма: {order_amount_text(order)}\n"
        f"Статус: {order_status_ru(order['status'])}\n"
        f"Дата: <code>{order['created_at']}</code>"
    )


async def send_main_menu(message: Message) -> None:
    await message.answer(MENU_TEXT, reply_markup=main_menu_kb())


async def notify_admin_order(bot: Bot, order_id: int) -> None:
    order = get_order(order_id)
    if not order:
        return
    await notify_admins(bot, format_order_for_admin(order), reply_markup=admin_order_kb(order_id))


async def finish_order_from_state(callback: CallbackQuery, state: FSMContext, payment_method: str) -> None:
    data = await state.get_data()
    category = data.get("category", "order")
    product = data.get("product", "Заявка")
    details = data.get("details", "")
    price = float(data.get("price", 0) or 0)

    if payment_method == "balance" and price > 0:
        user = get_user(callback.from_user.id)
        balance = float(user["balance"] if user else 0)
        if balance < price:
            await callback.message.answer(
                f"❌ Недостаточно средств на балансе.\n\n"
                f"Нужно: <b>{format_money(price, 'KZT')}</b>\n"
                f"Ваш баланс: <b>{format_money(balance, 'KZT')}</b>\n\n"
                f"Баланс внутри бота хранится в ₸. Пополните баланс или создайте заявку с ручной оплатой.",
                reply_markup=top_up_kb(),
            )
            await callback.answer()
            return

        order_id = create_order(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            category=category,
            product=product,
            details=details,
            price=price,
            payment_method="balance",
            status="paid",
            currency="KZT",
            display_amount=price,
        )
        change_balance(callback.from_user.id, -price, f"Оплата заказа #{order_id}", order_id)
    else:
        payment_currency = "RUB" if payment_method == "manual_rub" else "KZT"
        order_id = create_order(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            category=category,
            product=product,
            details=details,
            price=price,
            payment_method=payment_method,
            status="new",
            currency=payment_currency,
            display_amount=kzt_to_currency(price, payment_currency),
        )

    await notify_admin_order(callback.bot, order_id)
    await state.clear()

    if payment_method == "balance" and price > 0:
        payment_text = "Оплата списана с вашего баланса."
        amount_text = format_money(price, "KZT")
    else:
        payment_currency = "RUB" if payment_method == "manual_rub" else "KZT"
        amount_text = format_money(price, payment_currency)
        extra = ""
        if payment_currency == "RUB":
            extra = f"\nЭквивалент в тенге: <b>{format_money(price, 'KZT')}</b>"
        else:
            extra = f"\nЭквивалент в рублях: <b>{format_money(price, 'RUB')}</b>"
        payment_text = (
            f"Вы выбрали ручную оплату в <b>{'рублях' if payment_currency == 'RUB' else 'тенге'}</b>.\n"
            f"Сумма к оплате: <b>{amount_text}</b>{extra}\n\n"
            "После оплаты отправьте чек/скрин в поддержку или администратору.\n\n"
            "Реквизиты:\n"
            f"<blockquote>{safe(payment_details_for(payment_currency))}</blockquote>"
        )

    await callback.message.answer(
        f"✅ Заявка <b>#{order_id}</b> создана.\n\n"
        f"📦 {safe(product)}\n"
        f"💵 {amount_text}\n\n"
        f"{payment_text}",
        reply_markup=back_menu_kb(),
    )
    await callback.answer("Заявка создана")

async def pay_referral_bonus(bot: Bot, order: Any) -> None:
    if int(order["reward_paid"] or 0) == 1:
        return
    price = float(order["price"] or 0)
    if price <= 0 or order["category"] == "top_up":
        mark_reward_paid(int(order["id"]))
        return
    buyer = get_user(int(order["user_id"]))
    if not buyer or not buyer["ref_by"]:
        mark_reward_paid(int(order["id"]))
        return
    ref_by = int(buyer["ref_by"])
    reward = round(price * settings.referral_bonus_percent / 100, 2)
    if reward <= 0:
        mark_reward_paid(int(order["id"]))
        return
    change_balance(ref_by, reward, f"Реферальный бонус за заказ #{order['id']}", int(order["id"]))
    mark_reward_paid(int(order["id"]))
    try:
        await bot.send_message(ref_by, f"🤝 Вам начислен реферальный бонус: <b>{money(reward)}</b>")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cannot notify referrer %s: %s", ref_by, exc)


# =========================
# USER COMMANDS
# =========================


@router.message(CommandStart())
async def start_handler(message: Message, command: CommandObject) -> None:
    ref_by = None
    args = command.args or ""
    if args.startswith("ref_"):
        try:
            ref_by = int(args.replace("ref_", "", 1))
        except ValueError:
            ref_by = None

    was_new = upsert_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
        ref_by=ref_by,
    )
    if was_new:
        await notify_admins(
            message.bot,
            "👤 <b>Новый пользователь</b>\n\n"
            f"Username: @{safe(message.from_user.username) if message.from_user.username else 'не указан'}\n"
            f"Имя: {safe(message.from_user.full_name)}\n"
            f"ID: <code>{message.from_user.id}</code>\n"
            f"Дата: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>",
        )
    await message.answer("Добро пожаловать 👋", reply_markup=bottom_menu_kb())
    await send_main_menu(message)


@router.message(Command("check_support"))
async def check_support_handler(message: Message) -> None:
    await message.answer(
        f"SUPPORT_USERNAME сейчас: @{safe(settings.support_username)}\n"
        f"Railway должен быть: SUPPORT_USERNAME={safe(settings.support_username)}"
    )


@router.message(Command("menu"))
@router.message(F.text == "📋 Меню")
async def menu_handler(message: Message, state: FSMContext) -> None:
    upsert_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    await state.clear()
    await send_main_menu(message)


@router.message(F.text == "📦 Мои заказы")
async def my_orders_text_handler(message: Message) -> None:
    orders = get_user_orders(message.from_user.id, limit=10)
    if not orders:
        await message.answer("У вас пока нет заказов.", reply_markup=back_menu_kb())
        return
    await message.answer(
        "<b>📦 Мои заказы</b>\n\nНажмите на заказ, чтобы посмотреть детали и статус.",
        reply_markup=user_orders_kb(orders),
    )


@router.message(F.text == "📞 Поддержка")
async def support_text_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(support_panel_text(message.from_user.id), reply_markup=support_panel_kb())


@router.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=bottom_menu_kb())


@router.callback_query(F.data == "cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Действие отменено.", reply_markup=back_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "back_menu")
async def back_menu_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(MENU_TEXT, reply_markup=main_menu_kb())
    await callback.answer()


# =========================
# PROFILE / ORDERS / TOP
# =========================


@router.message(F.text == "👤 Профиль")
@router.callback_query(F.data == "profile")
async def profile_handler(event: Message | CallbackQuery) -> None:
    user = event.from_user
    upsert_user(user.id, user.username, user.full_name)
    db_user = get_user(user.id)
    balance = float(db_user["balance"] if db_user else 0)
    activity = get_user_activity_stats(user.id)

    bot_username = settings.bot_username
    if not bot_username and isinstance(event, CallbackQuery):
        me = await event.bot.get_me()
        bot_username = me.username or "your_bot"
    elif not bot_username and isinstance(event, Message):
        me = await event.bot.get_me()
        bot_username = me.username or "your_bot"

    text = (
        "<b>👤 Ваш профиль</b>\n\n"
        f"ID: <code>{user.id}</code>\n"
        f"Username: @{safe(user.username) if user.username else 'не указан'}\n"
        f"Валюта интерфейса: <b>{user_currency(user.id)}</b>\n"
        f"Баланс: <b>{format_money(balance, 'KZT')} / {format_money(balance, 'RUB')}</b>\n"
        f"Заказов всего: <b>{activity['orders_count']}</b>\n"
        f"Выполнено: <b>{activity['done_orders']}</b>\n"
        f"Покупок на сумму: <b>{format_money(activity['total_spent'], 'KZT')} / {format_money(activity['total_spent'], 'RUB')}</b>\n"
        f"Приглашено людей: <b>{activity['refs_count']}</b>\n\n"
        "<b>🤝 Партнёрская ссылка</b>\n"
        f"https://t.me/{bot_username}?start=ref_{user.id}\n"
        f"Бонус партнёру: <b>{settings.referral_bonus_percent:g}%</b> от выполненного заказа."
    )

    if isinstance(event, CallbackQuery):
        await event.message.answer(text, reply_markup=profile_kb())
        await event.answer()
    else:
        await event.answer(text, reply_markup=profile_kb())


@router.message(Command("currency"))
@router.message(F.text == "🌍 Валюта")
async def currency_message_handler(message: Message) -> None:
    upsert_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    current = user_currency(message.from_user.id)
    await message.answer(
        "<b>🌍 Валюта</b>\n\n"
        "Выберите удобную валюту для отображения цен и ручной оплаты.\n"
        f"Текущая валюта: <b>{current}</b>\n\n"
        f"Курс для расчёта: <b>1 ₽ = {settings.rub_to_kzt_rate:g}₸</b>.",
        reply_markup=currency_choice_kb(current),
    )


@router.callback_query(F.data == "currency")
async def currency_callback_handler(callback: CallbackQuery) -> None:
    upsert_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    current = user_currency(callback.from_user.id)
    await callback.message.answer(
        "<b>🌍 Валюта</b>\n\n"
        "Выберите удобную валюту для отображения цен и ручной оплаты.\n"
        f"Текущая валюта: <b>{current}</b>\n\n"
        f"Курс для расчёта: <b>1 ₽ = {settings.rub_to_kzt_rate:g}₸</b>.",
        reply_markup=currency_choice_kb(current),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_currency:"))
async def set_currency_handler(callback: CallbackQuery) -> None:
    code = normalize_currency(callback.data.split(":", 1)[1])
    set_user_currency(callback.from_user.id, code)
    await callback.message.answer(
        f"✅ Валюта изменена на <b>{'тенге ₸' if code == 'KZT' else 'рубли ₽'}</b>.\n\n"
        "Цены в боте будут показываться с учётом этой валюты, а ручную оплату можно выбрать в ₸ или ₽ при оформлении заказа.",
        reply_markup=back_menu_kb(),
    )
    await callback.answer("Валюта сохранена")




@router.callback_query(F.data == "my_orders")
async def my_orders_handler(callback: CallbackQuery) -> None:
    orders = get_user_orders(callback.from_user.id, limit=10)
    if not orders:
        await callback.message.answer("У вас пока нет заказов.", reply_markup=back_menu_kb())
        await callback.answer()
        return

    text = (
        "<b>📦 Мои заказы</b>\n\n"
        "Нажмите на заказ, чтобы посмотреть детали, статус и кнопку проверки TON-оплаты."
    )
    await callback.message.answer(text, reply_markup=user_orders_kb(orders))
    await callback.answer()


@router.callback_query(F.data.startswith("user_order:"))
async def user_order_details_handler(callback: CallbackQuery) -> None:
    order_id = int(callback.data.split(":", 1)[1])
    order = get_order(order_id)
    if not order or int(order["user_id"]) != callback.from_user.id:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    invoice = get_ton_invoice_by_order(order_id)
    extra = ""
    if invoice:
        extra = (
            "\n\n<b>💎 TON-счёт</b>\n"
            f"Сумма TON: <b>{float(invoice['amount_ton']):g} TON</b>\n"
            f"Комментарий: <code>{safe(invoice['comment'])}</code>\n"
            f"Статус оплаты: <b>{safe(invoice['status'])}</b>"
        )

    await callback.message.answer(
        format_order_for_user(order) + extra,
        reply_markup=user_order_kb(order_id, str(order["status"])),
    )
    await callback.answer()


@router.callback_query(F.data == "top_clients")
async def top_clients_handler(callback: CallbackQuery) -> None:
    rows = top_clients(limit=10)
    if not rows:
        await callback.message.answer("🏆 Топ клиентов пока пуст. Выполненные заказы появятся здесь.", reply_markup=back_menu_kb())
        await callback.answer()
        return
    lines = ["<b>🏆 Топ клиентов</b>\n"]
    for i, row in enumerate(rows, start=1):
        name = f"@{safe(row['username'])}" if row["username"] else safe(row["full_name"] or row["user_id"])
        lines.append(f"{i}. {name} — {int(row['orders_count'])} заказ(ов), {money(float(row['total_spent'] or 0))}")
    await callback.message.answer("\n".join(lines), reply_markup=back_menu_kb())
    await callback.answer()


# =========================
# PRODUCTS
# =========================


@router.callback_query(F.data == "buy_stars")
async def buy_stars_handler(callback: CallbackQuery) -> None:
    await callback.message.edit_text("⭐ Выберите количество Telegram Stars:", reply_markup=stars_packages_kb())
    await callback.answer()


@router.callback_query(F.data == "premium")
async def premium_handler(callback: CallbackQuery) -> None:
    await callback.message.edit_text("👑 Выберите срок Telegram Premium:", reply_markup=premium_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("fixed:"))
async def fixed_product_handler(callback: CallbackQuery, state: FSMContext) -> None:
    _, kind, code = callback.data.split(":", 2)

    if not is_product_enabled(f"{kind}:{code}"):
        await callback.answer("Товар временно недоступен", show_alert=True)
        return

    if kind == "stars":
        price = get_product_price("stars", code, STARS_PACKAGES[code])
        product = f"Telegram Stars — {code} Stars"
        prompt = "Введите @username получателя или ссылку на профиль Telegram."
        category = "Telegram Stars"
    elif kind == "premium":
        price = get_product_price("premium", code, PREMIUM_PACKAGES[code])
        product = f"Telegram Premium — {code} мес."
        prompt = "Введите @username получателя Telegram Premium."
        category = "Telegram Premium"
    else:
        await callback.answer("Неизвестный товар", show_alert=True)
        return

    await state.set_state(OrderFSM.waiting_details)
    await state.update_data(category=category, product=product, price=price)
    await callback.message.answer(
        f"<b>{safe(product)}</b>\n"
        f"Цена: <b>{money_multi(price)}</b>\n\n"
        f"{prompt}",
        reply_markup=back_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("custom:"))
async def custom_product_handler(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    if not is_product_enabled(f"custom:{key}"):
        await callback.answer("Раздел временно недоступен", show_alert=True)
        return
    item = CUSTOM_PRODUCTS.get(key)
    if not item:
        await callback.answer("Раздел не найден", show_alert=True)
        return
    await state.set_state(OrderFSM.waiting_details)
    await state.update_data(category=item["title"], product=item["title"], price=0)
    await callback.message.answer(f"<b>{safe(item['title'])}</b>\n\n{safe(item['prompt'])}", reply_markup=back_menu_kb())
    await callback.answer()


@router.message(OrderFSM.waiting_details)
async def order_details_handler(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 3:
        await message.answer("Напишите детали заказа подробнее.")
        return

    data = await state.get_data()
    await state.update_data(details=text)
    price = float(data.get("price", 0) or 0)
    product = data.get("product", "Заявка")

    if price <= 0:
        await state.set_state(OrderFSM.waiting_custom_price)
        await message.answer(
            f"<b>{safe(product)}</b>\n\n"
            f"📝 Детали: {safe(text)}\n\n"
            "Введите сумму заказа в тенге или рублях.\n"
            "Пример: <code>2500</code> или <code>500₽</code>",
            reply_markup=back_menu_kb(),
        )
        return

    await state.set_state(OrderFSM.waiting_payment)
    await message.answer(
        f"<b>Проверьте заявку</b>\n\n"
        f"📦 Товар: <b>{safe(product)}</b>\n"
        f"💵 Цена: <b>{money_multi(price)}</b>\n"
        f"📝 Детали: {safe(text)}\n\n"
        f"Выберите способ оформления:",
        reply_markup=payment_choice_kb(price),
    )


@router.message(OrderFSM.waiting_custom_price)
async def order_custom_price_handler(message: Message, state: FSMContext) -> None:
    try:
        price, detected_currency, original_amount = parse_amount(message.text or "", user_currency(message.from_user.id))
    except ValueError:
        await message.answer("Введите сумму цифрами. Пример: 2500 или 500₽")
        return

    data = await state.get_data()
    await state.update_data(price=price, input_currency=detected_currency, input_amount=original_amount)
    await state.set_state(OrderFSM.waiting_payment)

    product = data.get("product", "Заявка")
    details = data.get("details", "")
    await message.answer(
        f"<b>Проверьте заявку</b>\n\n"
        f"📦 Товар: <b>{safe(product)}</b>\n"
        f"💵 Цена: <b>{money_multi(price)}</b>\n"
        f"📝 Детали: {safe(details)}\n\n"
        "Выберите способ оформления:",
        reply_markup=payment_choice_kb(price),
    )


@router.callback_query(StateFilter(OrderFSM.waiting_payment), F.data == "pay:balance")
async def pay_balance_handler(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("category") == "top_up":
        await callback.answer("Пополнение нельзя оплатить внутренним балансом", show_alert=True)
        return
    await finish_order_from_state(callback, state, "balance")


@router.callback_query(StateFilter(OrderFSM.waiting_payment), F.data.in_({"pay:manual", "pay:manual_kzt", "pay:manual_rub"}))
async def pay_manual_handler(callback: CallbackQuery, state: FSMContext) -> None:
    method = callback.data.split(":", 1)[1]
    if method == "manual":
        method = "manual_kzt"
    await finish_order_from_state(callback, state, method)


# =========================
# PUBG
# =========================


@router.callback_query(F.data == "pubg")
async def pubg_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PubgFSM.waiting_pubg_id)
    await callback.message.answer("🎮 Введите PUBG ID клиента.\n\nПример: <code>5123456789</code>", reply_markup=back_menu_kb())
    await callback.answer()


@router.message(PubgFSM.waiting_pubg_id)
async def pubg_id_handler(message: Message, state: FSMContext) -> None:
    pubg_id = (message.text or "").strip()
    if not pubg_id.isdigit() or len(pubg_id) < 5:
        await message.answer("❌ Введите корректный PUBG ID. Только цифры, минимум 5 символов.")
        return
    await state.update_data(pubg_id=pubg_id)
    await message.answer(f"PUBG ID: <code>{pubg_id}</code>\n\nТеперь выберите пакет UC:", reply_markup=pubg_packages_kb())


@router.callback_query(F.data.startswith("pubg_pack:"))
async def pubg_package_handler(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    pubg_id = data.get("pubg_id")
    if not pubg_id:
        await state.set_state(PubgFSM.waiting_pubg_id)
        await callback.message.answer("Сначала введите PUBG ID.")
        await callback.answer()
        return
    uc = callback.data.split(":", 1)[1]
    if not is_product_enabled(f"pubg:{uc}"):
        await callback.answer("Этот пакет временно недоступен", show_alert=True)
        return
    price = get_product_price("pubg", uc, PUBG_PACKAGES[uc])
    await state.set_state(OrderFSM.waiting_payment)
    await state.update_data(
        category="PUBG UC",
        product=f"PUBG UC — {uc} UC",
        price=price,
        details=f"PUBG ID: {pubg_id}, пакет: {uc} UC",
    )
    await callback.message.answer(
        f"<b>Проверьте заявку</b>\n\n"
        f"🎮 PUBG ID: <code>{safe(pubg_id)}</code>\n"
        f"📦 Пакет: <b>{uc} UC</b>\n"
        f"💵 Цена: <b>{money_multi(price)}</b>\n\n"
        f"Выберите способ оформления:",
        reply_markup=payment_choice_kb(price),
    )
    await callback.answer()


# =========================
# TOP UP / SUPPORT
# =========================


@router.callback_query(F.data == "top_up_balance")
async def top_up_handler(callback: CallbackQuery) -> None:
    await callback.message.edit_text("💰 Выберите сумму пополнения:", reply_markup=top_up_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("topup_amount:"))
async def topup_amount_handler(callback: CallbackQuery, state: FSMContext) -> None:
    amount = float(callback.data.split(":", 1)[1])
    await state.set_state(OrderFSM.waiting_payment)
    await state.update_data(
        category="top_up",
        product="Пополнение баланса",
        details=f"Пополнение баланса на {money_multi(amount)}",
        price=amount,
    )
    await callback.message.answer(
        f"<b>💰 Пополнение баланса</b>\n\n"
        f"Сумма: <b>{money_multi(amount)}</b>\n\n"
        "Выберите способ оплаты:",
        reply_markup=payment_choice_kb(amount),
    )
    await callback.answer()

@router.callback_query(F.data == "topup_custom")
async def topup_custom_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TopUpFSM.waiting_amount)
    await callback.message.answer("Введите сумму пополнения цифрами в ₸ или ₽.\n\nПример: 1500 или 250₽")
    await callback.answer()


@router.message(TopUpFSM.waiting_amount)
async def topup_custom_amount_handler(message: Message, state: FSMContext) -> None:
    try:
        amount, detected_currency, original_amount = parse_amount(message.text or "", user_currency(message.from_user.id))
    except ValueError:
        await message.answer("Введите сумму цифрами. Пример: 1500 или 250₽")
        return

    await state.set_state(OrderFSM.waiting_payment)
    await state.update_data(
        category="top_up",
        product="Пополнение баланса",
        details=f"Пополнение баланса на {money_multi(amount)}",
        price=amount,
        input_currency=detected_currency,
        input_amount=original_amount,
    )
    await message.answer(
        f"<b>💰 Пополнение баланса</b>\n\n"
        f"Сумма: <b>{money_multi(amount)}</b>\n\n"
        "Выберите способ оплаты:",
        reply_markup=payment_choice_kb(amount),
    )
@router.callback_query(F.data == "promo")
async def promo_disabled_handler(callback: CallbackQuery) -> None:
    await callback.answer("Промокоды отключены", show_alert=True)

def support_panel_text(user_id: int) -> str:
    stats = count_user_support_tickets(user_id)
    active = stats.get("open", 0)
    total = stats.get("total", 0)
    status_line = (
        "✅ Вы можете создать новый тикет или открыть старый диалог."
        if active == 0
        else "⚠️ У вас есть активный тикет. Можно открыть его и продолжить переписку."
    )
    return (
        "<b>📞 Техническая поддержка</b>\n\n"
        "Здесь можно создать тикет, посмотреть историю обращений и продолжить переписку с администратором.\n\n"
        "<b>📊 Статистика:</b>\n"
        f"• Активных тикетов: <b>{active}</b>\n"
        f"• Всего тикетов: <b>{total}</b>\n\n"
        f"{status_line}"
    )


def format_ticket_history(ticket_id: int, for_admin: bool = False, limit: int = 12) -> str:
    ticket = get_support_ticket(ticket_id)
    if not ticket:
        return "Тикет не найден."

    messages = get_ticket_messages(ticket_id, limit=limit)
    status = ticket_status_ru(ticket["status"])
    header = (
        f"<b>🆘 Тикет #{ticket_id}</b>\n"
        f"Статус: <b>{safe(status)}</b>\n"
        f"Клиент: {user_mention(ticket['username'], int(ticket['user_id']))}\n"
        f"Создан: <code>{safe(ticket['created_at'])}</code>\n\n"
        if for_admin
        else (
            f"<b>📨 Ваш тикет #{ticket_id}</b>\n"
            f"Статус: <b>{safe(status)}</b>\n"
            f"Создан: <code>{safe(ticket['created_at'])}</code>\n\n"
        )
    )

    if not messages:
        return header + "История пока пустая."

    lines = [header, "<b>История переписки:</b>"]
    for msg in messages:
        sender = "👤 Клиент" if msg["sender"] == "user" else "🛠 Поддержка"
        lines.append(f"\n<b>{sender}</b> <code>{safe(msg['created_at'])}</code>\n{safe(msg['message'])}")

    return "\n".join(lines)


def ticket_admin_notice(ticket_id: int, ticket: Any, text: str, is_reply: bool = False) -> str:
    title = "💬 Новое сообщение в тикете" if is_reply else "🆘 Новый тикет поддержки"
    return (
        f"<b>{title} #{ticket_id}</b>\n\n"
        f"👤 Клиент: {user_mention(ticket['username'], int(ticket['user_id']))}\n"
        f"🆔 User ID: <code>{ticket['user_id']}</code>\n"
        f"🔗 Username: @{safe(ticket['username']) if ticket['username'] else 'не указан'}\n\n"
        f"<b>Сообщение:</b>\n{safe(text)}\n\n"
        f"Ответить можно кнопкой ниже или командой:\n<code>/ticket_reply {ticket_id} ваш текст</code>"
    )


@router.callback_query(F.data == "support")
async def support_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(
        support_panel_text(callback.from_user.id),
        reply_markup=support_panel_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "support_create")
async def support_create_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SupportFSM.waiting_message)
    await callback.message.answer(
        "<b>📝 Новый тикет</b>\n\n"
        "Опишите проблему одним сообщением.\n"
        "Например: номер заказа, что хотели купить, что не получилось или какую ошибку видите.",
        reply_markup=back_menu_kb(),
    )
    await callback.answer()


@router.message(SupportFSM.waiting_message)
async def support_message_handler(message: Message, state: FSMContext) -> None:
    text = (message.text or message.caption or "").strip()
    if len(text) < 3:
        await message.answer("Напишите вопрос подробнее одним сообщением.")
        return

    upsert_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    ticket_id = create_support_ticket(message.from_user.id, message.from_user.username, text)
    ticket = get_support_ticket(ticket_id)

    if ticket:
        await notify_admins(
            message.bot,
            ticket_admin_notice(ticket_id, ticket, text, is_reply=False),
            reply_markup=admin_ticket_kb(ticket_id),
        )

    await state.clear()
    await message.answer(
        f"✅ Тикет <b>#{ticket_id}</b> создан.\n\n"
        "Ваше сообщение отправлено администратору. Ответ придёт прямо сюда.\n"
        "Вы также можете открыть тикет и продолжить переписку.",
        reply_markup=user_ticket_kb(ticket_id),
    )


@router.callback_query(F.data == "support_my_tickets")
async def support_my_tickets_handler(callback: CallbackQuery) -> None:
    tickets = list_user_support_tickets(callback.from_user.id, limit=8)
    if not tickets:
        await callback.message.answer(
            "У вас пока нет тикетов поддержки.",
            reply_markup=support_panel_kb(),
        )
        await callback.answer()
        return

    rows = []
    text_lines = ["<b>📋 Мои тикеты</b>\n"]
    for ticket in tickets:
        status = ticket_status_ru(ticket["status"])
        text_lines.append(
            f"#{ticket['id']} — <b>{safe(status)}</b> — {safe(ticket['created_at'])}"
        )
        rows.append([InlineKeyboardButton(
            text=f"#{ticket['id']} — {status}",
            callback_data=f"support_ticket_view:{ticket['id']}",
        )])
    rows.append([InlineKeyboardButton(text="📝 Создать тикет", callback_data="support_create")])
    rows.append([InlineKeyboardButton(text="⬅️ В поддержку", callback_data="support")])

    await callback.message.answer(
        "\n".join(text_lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("support_ticket_view:"))
async def support_ticket_view_handler(callback: CallbackQuery) -> None:
    ticket_id = int(callback.data.split(":", 1)[1])
    ticket = get_support_ticket(ticket_id)
    if not ticket or int(ticket["user_id"]) != callback.from_user.id:
        await callback.answer("Тикет не найден", show_alert=True)
        return

    await callback.message.answer(
        format_ticket_history(ticket_id, for_admin=False),
        reply_markup=user_ticket_kb(ticket_id, is_closed=ticket["status"] == "closed"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("support_ticket_reply:"))
async def support_ticket_reply_button_handler(callback: CallbackQuery, state: FSMContext) -> None:
    ticket_id = int(callback.data.split(":", 1)[1])
    ticket = get_support_ticket(ticket_id)
    if not ticket or int(ticket["user_id"]) != callback.from_user.id:
        await callback.answer("Тикет не найден", show_alert=True)
        return
    if ticket["status"] == "closed":
        await callback.answer("Этот тикет уже закрыт", show_alert=True)
        return

    await state.set_state(SupportFSM.waiting_ticket_reply)
    await state.update_data(ticket_id=ticket_id)
    await callback.message.answer(
        f"✍️ Напишите сообщение в тикет <b>#{ticket_id}</b> одним сообщением.\n\n"
        "Для отмены используйте /cancel",
        reply_markup=back_menu_kb(),
    )
    await callback.answer()


@router.message(SupportFSM.waiting_ticket_reply)
async def support_ticket_reply_text_handler(message: Message, state: FSMContext) -> None:
    text = (message.text or message.caption or "").strip()
    if len(text) < 2:
        await message.answer("Сообщение слишком короткое. Напишите подробнее или /cancel.")
        return

    data = await state.get_data()
    ticket_id = int(data.get("ticket_id", 0))
    ticket = add_support_message(ticket_id, "user", message.from_user.id, message.from_user.username, text)
    await state.clear()

    if not ticket:
        await message.answer("❌ Тикет не найден или уже закрыт.")
        return

    await notify_admins(
        message.bot,
        ticket_admin_notice(ticket_id, ticket, text, is_reply=True),
        reply_markup=admin_ticket_kb(ticket_id),
    )

    await message.answer(
        f"✅ Сообщение добавлено в тикет <b>#{ticket_id}</b>.\n"
        "Администратор получил уведомление.",
        reply_markup=user_ticket_kb(ticket_id),
    )


@router.callback_query(F.data.startswith("support_ticket_close:"))
async def support_ticket_close_handler(callback: CallbackQuery) -> None:
    ticket_id = int(callback.data.split(":", 1)[1])
    ticket = get_support_ticket(ticket_id)
    if not ticket or int(ticket["user_id"]) != callback.from_user.id:
        await callback.answer("Тикет не найден", show_alert=True)
        return

    ok = close_support_ticket(ticket_id)
    if not ok:
        await callback.answer("Не удалось закрыть тикет", show_alert=True)
        return

    await notify_admins(
        callback.bot,
        f"✅ Клиент закрыл тикет поддержки <b>#{ticket_id}</b>.\n"
        f"Клиент: {user_mention(ticket['username'], int(ticket['user_id']))}"
    )

    await callback.message.answer(
        f"✅ Тикет <b>#{ticket_id}</b> закрыт.",
        reply_markup=support_panel_kb(),
    )
    await callback.answer("Тикет закрыт")


@router.callback_query(F.data.startswith("admin_ticket_history:"))
async def admin_ticket_history_handler(callback: CallbackQuery) -> None:
    if not can_manage_support(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    ticket_id = int(callback.data.split(":", 1)[1])
    ticket = get_support_ticket(ticket_id)
    if not ticket:
        await callback.answer("Тикет не найден", show_alert=True)
        return

    await callback.message.answer(
        format_ticket_history(ticket_id, for_admin=True),
        reply_markup=admin_ticket_kb(ticket_id) if ticket["status"] != "closed" else admin_panel_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ticket_reply:"))
async def admin_ticket_reply_button_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not can_manage_support(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    ticket_id = int(callback.data.split(":", 1)[1])
    ticket = get_support_ticket(ticket_id)
    if not ticket:
        await callback.answer("Тикет не найден", show_alert=True)
        return
    if ticket["status"] == "closed":
        await callback.answer("Этот тикет уже закрыт", show_alert=True)
        return

    await state.set_state(AdminTicketFSM.waiting_reply)
    await state.update_data(ticket_id=ticket_id)
    await callback.message.answer(
        f"✉️ Введите ответ на тикет <b>#{ticket_id}</b> одним сообщением.\n\n"
        f"Клиент: {user_mention(ticket['username'], int(ticket['user_id']))}\n"
        f"Последнее сообщение: {safe(ticket['message'])}\n\n"
        "Для отмены используйте /cancel"
    )
    await callback.answer()


@router.message(AdminTicketFSM.waiting_reply)
async def admin_ticket_reply_text_handler(message: Message, state: FSMContext) -> None:
    if not can_manage_support(message.from_user.id):
        return

    reply_text = (message.text or message.caption or "").strip()
    if len(reply_text) < 2:
        await message.answer("Ответ слишком короткий. Напишите ответ одним сообщением или /cancel.")
        return

    data = await state.get_data()
    ticket_id = int(data.get("ticket_id", 0))
    ticket = answer_support_ticket(ticket_id, reply_text)
    await state.clear()

    if not ticket:
        await message.answer("❌ Тикет не найден или уже закрыт.")
        return

    user_id = int(ticket["user_id"])
    try:
        await message.bot.send_message(
            user_id,
            f"<b>📞 Ответ поддержки по тикету #{ticket_id}</b>\n\n"
            f"{safe(reply_text)}\n\n"
            "Вы можете продолжить переписку через раздел <b>📞 Поддержка → 📋 Мои тикеты</b>.",
            reply_markup=user_ticket_kb(ticket_id),
        )
        await message.answer(
            f"✅ Ответ по тикету <b>#{ticket_id}</b> отправлен клиенту.",
            reply_markup=admin_ticket_kb(ticket_id),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send ticket reply to %s: %s", user_id, exc)
        await message.answer(
            f"⚠️ Ответ сохранён, но не удалось отправить клиенту. Возможно, клиент заблокировал бота.\n"
            f"Тикет: <b>#{ticket_id}</b>"
        )


@router.message(Command("ticket_reply"))
async def admin_ticket_reply_command_handler(message: Message) -> None:
    if not can_manage_support(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Формат: <code>/ticket_reply TICKET_ID текст ответа</code>")
        return

    try:
        ticket_id = int(parts[1])
    except ValueError:
        await message.answer("TICKET_ID должен быть числом.")
        return

    reply_text = parts[2].strip()
    ticket = answer_support_ticket(ticket_id, reply_text)
    if not ticket:
        await message.answer("❌ Тикет не найден или уже закрыт.")
        return

    user_id = int(ticket["user_id"])
    try:
        await message.bot.send_message(
            user_id,
            f"<b>📞 Ответ поддержки по тикету #{ticket_id}</b>\n\n"
            f"{safe(reply_text)}\n\n"
            "Вы можете продолжить переписку через раздел <b>📞 Поддержка → 📋 Мои тикеты</b>.",
            reply_markup=user_ticket_kb(ticket_id),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send ticket reply to %s: %s", user_id, exc)
        await message.answer("⚠️ Ответ сохранён, но не удалось отправить клиенту. Возможно, клиент заблокировал бота.")
        return

    await message.answer(f"✅ Ответ по тикету <b>#{ticket_id}</b> отправлен клиенту.", reply_markup=admin_ticket_kb(ticket_id))


@router.callback_query(F.data.startswith("admin_ticket_close:"))
async def admin_ticket_close_handler(callback: CallbackQuery) -> None:
    if not can_manage_support(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    ticket_id = int(callback.data.split(":", 1)[1])
    ticket = get_support_ticket(ticket_id)
    ok = close_support_ticket(ticket_id)
    if not ok or not ticket:
        await callback.answer("Тикет не найден", show_alert=True)
        return

    await callback.message.edit_text((callback.message.text or "") + "\n\n✅ Тикет закрыт администратором.")
    try:
        await callback.bot.send_message(
            int(ticket["user_id"]),
            f"✅ Ваш тикет поддержки <b>#{ticket_id}</b> закрыт.\n\n"
            "Если вопрос снова появится, создайте новый тикет в разделе поддержки.",
        )
    except Exception:
        pass
    await callback.answer("Тикет закрыт")


@router.callback_query(F.data == "admin_tickets")
async def admin_tickets_handler(callback: CallbackQuery) -> None:
    if not can_manage_support(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    tickets = list_active_support_tickets(limit=10)
    if not tickets:
        await callback.message.answer("Активных тикетов нет.", reply_markup=admin_panel_kb(admin_role(callback.from_user.id)))
        await callback.answer()
        return

    rows = []
    lines = ["<b>🆘 Активные тикеты</b>\n"]
    for ticket in tickets:
        status = ticket_status_ru(ticket["status"])
        lines.append(
            f"#{ticket['id']} — {user_mention(ticket['username'], int(ticket['user_id']))} — <b>{safe(status)}</b>"
        )
        rows.append([InlineKeyboardButton(
            text=f"#{ticket['id']} — {status}",
            callback_data=f"admin_ticket_history:{ticket['id']}",
        )])
    rows.append([InlineKeyboardButton(text="⬅️ В админку", callback_data="admin_stats")])

    await callback.message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data == "calculator")
async def calculator_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    lines = ["<b>🧮 Калькулятор цены</b>\n"]
    lines.append("Выберите, что хотите посчитать. Бот сам рассчитает сумму по текущему прайсу.\n")
    lines.append("<b>Готовые цены:</b>")
    stars_prices = current_package_prices("stars", STARS_PACKAGES)
    premium_prices = current_package_prices("premium", PREMIUM_PACKAGES)
    pubg_prices = current_package_prices("pubg", PUBG_PACKAGES)
    lines.append("Stars: " + ", ".join([f"{amount} — {money_multi(price)}" for amount, price in stars_prices.items()]))
    lines.append("Premium: " + ", ".join([f"{months} мес. — {money_multi(price)}" for months, price in premium_prices.items()]))
    lines.append("PUBG UC: " + ", ".join([f"{uc} — {money_multi(price)}" for uc, price in pubg_prices.items()]))
    await callback.message.answer("\n".join(lines), reply_markup=calculator_choice_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("calc:"))
async def calculator_type_handler(callback: CallbackQuery, state: FSMContext) -> None:
    kind = callback.data.split(":", 1)[1]
    await state.set_state(CalculatorFSM.waiting_amount)
    await state.update_data(calc_kind=kind)
    prompts = {
        "stars": "Введите количество Stars. Пример: 500",
        "uc": "Введите количество UC. Пример: 660",
        "premium": "Введите количество месяцев Premium. Пример: 6",
    }
    await callback.message.answer(prompts.get(kind, "Введите количество цифрами."), reply_markup=back_menu_kb())
    await callback.answer()


@router.message(CalculatorFSM.waiting_amount)
async def calculator_amount_handler(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").replace(" ", "").replace(",", ".")
    try:
        amount = int(float(raw))
    except ValueError:
        await message.answer("Введите число. Пример: 500")
        return
    if amount <= 0:
        await message.answer("Количество должно быть больше 0.")
        return
    data = await state.get_data()
    kind = data.get("calc_kind", "stars")
    if kind == "stars":
        price, note = estimate_package_price(current_package_prices("stars", STARS_PACKAGES), amount)
        title = f"⭐ {amount} Stars"
    elif kind == "uc":
        price, note = estimate_package_price(current_package_prices("pubg", PUBG_PACKAGES), amount)
        title = f"🎮 {amount} UC"
    else:
        price, note = estimate_package_price(current_package_prices("premium", PREMIUM_PACKAGES), amount)
        title = f"👑 Premium на {amount} мес."
    await state.clear()
    await message.answer(
        f"<b>🧮 Расчёт</b>\n\n"
        f"Товар: <b>{safe(title)}</b>\n"
        f"Цена: <b>{money_multi(price)}</b>\n"
        f"Тип расчёта: {safe(note)}\n\n"
        f"Для точного оформления нажмите кнопку ниже и выберите пакет.",
        reply_markup=calculator_result_kb(kind),
    )
@router.callback_query(F.data == "info")
async def info_handler(callback: CallbackQuery) -> None:
    await callback.message.answer(INFO_TEXT, reply_markup=back_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "faq")
async def faq_handler(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "<b>❓ Частые вопросы</b>\n\n"
        "<b>Как оплатить через TON?</b>\n"
        "Бот покажет адрес, точную сумму и комментарий. Комментарий обязателен.\n\n"
        "<b>Что делать, если оплатил без комментария?</b>\n"
        "Откройте заказ и нажмите кнопку <b>⚠️ Оплатил без комментария</b>.\n\n"
        "<b>Сколько ждать заказ?</b>\n"
        "После автоматической проверки оплаты заказ переходит в обработку. Время зависит от товара.\n\n"
        "<b>Где посмотреть статус?</b>\n"
        "Откройте <b>👤 Профиль → 📦 Мои заказы</b>.\n\n"
        "<b>Как написать поддержку?</b>\n"
        "Откройте <b>📞 Поддержка</b>, создайте тикет и опишите вопрос.",
        reply_markup=back_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "partner")
async def partner_handler(callback: CallbackQuery) -> None:
    bot_username = settings.bot_username
    if not bot_username:
        me = await callback.bot.get_me()
        bot_username = me.username or "your_bot"
    await callback.message.answer(
        f"<b>🤝 Партнёрская программа</b>\n\n"
        f"Вы получаете <b>{settings.referral_bonus_percent:g}%</b> на баланс с каждого выполненного заказа приглашённого клиента.\n\n"
        f"Ваша ссылка:\nhttps://t.me/{bot_username}?start=ref_{callback.from_user.id}",
        reply_markup=back_menu_kb(),
    )
    await callback.answer()


# =========================
# ADMIN
# =========================


@router.message(Command("admin"))
async def admin_handler(message: Message) -> None:
    if not can_manage_support(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    role = admin_role(message.from_user.id)
    await message.answer(
        f"<b>🛠 Админ-панель</b>\nРоль: <b>{admin_role_ru(message.from_user.id)}</b>",
        reply_markup=admin_panel_kb(role),
    )


@router.message(Command("ton_rate"))
async def admin_ton_rate_handler(message: Message) -> None:
    if not can_manage_orders(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    rate = await asyncio.to_thread(get_ton_rate_kzt, True)
    mode = "автоматический" if settings.ton_rate_auto_enabled else "ручной"
    await message.answer(
        f"📈 <b>Курс TON</b>\n\n"
        f"Режим: <b>{mode}</b>\n"
        f"1 TON ≈ <b>{money(rate)}</b>\n\n"
        f"Fallback в Railway: <code>TON_RATE_KZT={settings.ton_rate_kzt:g}</code>"
    )


@router.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: CallbackQuery) -> None:
    if not can_manage_orders(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    stats = get_admin_stats_expanded()
    await callback.message.answer(
        "<b>📊 Статистика GamePay</b>\n\n"
        f"👥 Пользователей: <b>{stats['users_count']}</b>\n"
        f"👤 Новых сегодня: <b>{stats['new_users_today']}</b>\n\n"
        f"📦 Заказов всего: <b>{stats['orders_count']}</b>\n"
        f"📦 Заказов сегодня: <b>{stats['orders_today']}</b>\n"
        f"⏳ Ожидают TON: <b>{stats['waiting_ton']}</b>\n"
        f"🛠 Активных заказов: <b>{stats['active_orders']}</b>\n"
        f"✅ Выполненных: <b>{stats['done_orders']}</b>\n"
        f"❌ Отменённых: <b>{stats['cancelled_orders']}</b>\n\n"
        f"💰 Оплачено сегодня: <b>{money(float(stats['paid_today']))}</b>\n"
        f"💰 Оплачено за месяц: <b>{money(float(stats['paid_month']))}</b>\n\n"
        f"🆘 Активных тикетов: <b>{stats['open_tickets']}</b>\n"
        f"⭐ Отзывов: <b>{stats['reviews_count']}</b>\n"
        f"⭐ Средняя оценка: <b>{stats['avg_rating']:.2f}</b>",
        reply_markup=admin_panel_kb(admin_role(callback.from_user.id)),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_products")
async def admin_products_handler(callback: CallbackQuery) -> None:
    if not can_manage_settings(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    items = list_product_items(include_disabled=True)
    await callback.message.answer(
        "<b>⚙️ Товары и цены</b>\n\n"
        "Нажмите на товар, чтобы изменить цену или включить/выключить его.",
        reply_markup=admin_products_kb(items),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_product:"))
async def admin_product_view_handler(callback: CallbackQuery) -> None:
    if not can_manage_settings(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    sku = callback.data.split(":", 1)[1]
    item = get_product_item(sku)
    if not item:
        await callback.answer("Товар не найден", show_alert=True)
        return
    status = "✅ включён" if int(item["enabled"] or 0) == 1 else "⛔ выключен"
    price = float(item["price"] or 0)
    await callback.message.answer(
        f"<b>⚙️ {safe(item['title'])}</b>\n\n"
        f"SKU: <code>{safe(item['sku'])}</code>\n"
        f"Тип: <b>{safe(item['kind'])}</b>\n"
        f"Цена: <b>{money(price) if price > 0 else 'договорная'}</b>\n"
        f"Статус: <b>{status}</b>",
        reply_markup=admin_product_kb(sku),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_product_price:"))
async def admin_product_price_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not can_manage_settings(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    sku = callback.data.split(":", 1)[1]
    item = get_product_item(sku)
    if not item:
        await callback.answer("Товар не найден", show_alert=True)
        return
    await state.set_state(AdminProductFSM.waiting_price)
    await state.update_data(sku=sku)
    await callback.message.answer(
        f"Введите новую цену для <b>{safe(item['title'])}</b> в тенге или рублях.\n\n"
        "Пример: <code>1500</code> или <code>250₽</code>\n"
        "Для товаров по договорённости можно поставить <code>0</code>.",
        reply_markup=back_menu_kb(),
    )
    await callback.answer()


@router.message(AdminProductFSM.waiting_price)
async def admin_product_price_text_handler(message: Message, state: FSMContext) -> None:
    if not can_manage_settings(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if raw in {"0", "0₸", "0р", "0₽"}:
        price = 0.0
    else:
        try:
            price, detected_currency, original_amount = parse_amount(raw, "KZT")
        except ValueError:
            await message.answer("Введите цену цифрами. Например: 1500 или 250₽")
            return
    if price < 0:
        await message.answer("Цена не может быть отрицательной.")
        return
    data = await state.get_data()
    sku = str(data.get("sku", ""))
    ok = set_product_price(sku, price)
    await state.clear()
    if not ok:
        await message.answer("❌ Товар не найден.", reply_markup=admin_panel_kb(admin_role(message.from_user.id)))
        return
    item = get_product_item(sku)
    await message.answer(
        f"✅ Цена обновлена.\n\n"
        f"Товар: <b>{safe(item['title']) if item else safe(sku)}</b>\n"
        f"Новая цена: <b>{money_multi(price) if price > 0 else 'договорная'}</b>",
        reply_markup=admin_product_kb(sku),
    )


@router.callback_query(F.data.startswith("admin_product_toggle:"))
async def admin_product_toggle_handler(callback: CallbackQuery) -> None:
    if not can_manage_settings(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    sku = callback.data.split(":", 1)[1]
    new_status = toggle_product_enabled(sku)
    if new_status is None:
        await callback.answer("Товар не найден", show_alert=True)
        return
    await callback.answer("Товар включён" if new_status else "Товар выключен", show_alert=True)
    item = get_product_item(sku)
    if item:
        status = "✅ включён" if new_status else "⛔ выключен"
        await callback.message.answer(
            f"<b>{safe(item['title'])}</b> теперь: <b>{status}</b>",
            reply_markup=admin_product_kb(sku),
        )


@router.callback_query(F.data == "admin_export")
async def admin_export_handler(callback: CallbackQuery) -> None:
    if not can_manage_settings(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer("Готовлю отчёты...")
    export_dir = tempfile.mkdtemp(prefix="gamepay_export_")
    files = []
    for table in ["users", "orders", "transactions", "refunds", "support_tickets", "ton_invoices", "reviews", "no_comment_reports"]:
        path = os.path.join(export_dir, f"{table}.csv")
        try:
            export_table_to_csv(table, path)
            files.append(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Export %s failed: %s", table, exc)
    for path in files:
        await callback.message.answer_document(FSInputFile(path))
    await callback.message.answer("✅ Экспорт готов.", reply_markup=admin_panel_kb(admin_role(callback.from_user.id)))


@router.callback_query(F.data == "admin_backup")
async def admin_backup_handler(callback: CallbackQuery) -> None:
    if not can_manage_settings(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if not os.path.exists(settings.db_path):
        await callback.answer("Файл базы пока не найден", show_alert=True)
        return
    await callback.message.answer_document(
        FSInputFile(settings.db_path, filename=f"gamepay_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db"),
        caption="💾 Бэкап базы GamePay",
    )
    await callback.answer("Бэкап отправлен")


@router.callback_query(F.data == "admin_orders")
async def admin_orders_handler(callback: CallbackQuery) -> None:
    if not can_manage_orders(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    orders = list_orders(limit=10)
    if not orders:
        await callback.message.answer("Новых заказов нет.", reply_markup=admin_panel_kb(admin_role(callback.from_user.id)))
        await callback.answer()
        return
    for order in orders:
        await callback.message.answer(format_order_for_admin(order), reply_markup=admin_order_kb(int(order["id"])))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_work:"))
async def admin_work_handler(callback: CallbackQuery) -> None:
    if not can_manage_orders(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order_id = int(callback.data.split(":", 1)[1])
    order = get_order(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    update_order_status(order_id, "work")
    try:
        await callback.message.edit_text(format_order_for_admin(get_order(order_id)), reply_markup=admin_order_kb(order_id))
    except Exception:
        pass
    await callback.bot.send_message(int(order["user_id"]), f"🟡 Ваш заказ <b>#{order_id}</b> взят в работу.")
    await callback.answer("В работе")


@router.callback_query(F.data.startswith("admin_done:"))
async def admin_done_handler(callback: CallbackQuery) -> None:
    if not can_manage_orders(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order_id = int(callback.data.split(":", 1)[1])
    order = get_order(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    if order["status"] == "done":
        await callback.answer("Уже выполнен", show_alert=True)
        return

    # Пополнение баланса начисляется только после подтверждения админом.
    if order["category"] == "top_up":
        change_balance(int(order["user_id"]), float(order["price"] or 0), f"Пополнение по заявке #{order_id}", order_id)

    update_order_status(order_id, "done")
    await pay_referral_bonus(callback.bot, get_order(order_id))

    try:
        await callback.message.edit_text(format_order_for_admin(get_order(order_id)), reply_markup=admin_order_kb(order_id))
    except Exception:
        pass
    await callback.bot.send_message(
        int(order["user_id"]),
        f"✅ Ваш заказ <b>#{order_id}</b> выполнен.\n\nСпасибо за покупку!",
    )
    await callback.answer("Заказ выполнен")


@router.callback_query(F.data.startswith("admin_cancel:"))
async def admin_cancel_handler(callback: CallbackQuery) -> None:
    if not can_manage_orders(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order_id = int(callback.data.split(":", 1)[1])
    order = get_order(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    if order["status"] == "cancelled":
        await callback.answer("Уже отменён", show_alert=True)
        return

    refund_text = ""
    if order["status"] == "done":
        await callback.answer("Выполненный заказ нельзя отменить этой кнопкой.", show_alert=True)
        return

    if order["payment_method"] == "balance":
        refund_amount = float(order["price"] or 0)
        if refund_amount > 0 and not get_refund_by_order(order_id):
            change_balance(int(order["user_id"]), refund_amount, f"Возврат за отмену заказа #{order_id}", order_id)
            create_refund_record(
                order_id=order_id,
                user_id=int(order["user_id"]),
                amount_kzt=refund_amount,
                method="balance",
                status="done",
                note="Возврат оплаты с внутреннего баланса",
            )
            refund_text = f"\n\n↩️ Сумма <b>{money(refund_amount)}</b> возвращена на ваш баланс."

    elif order["payment_method"] == "TON" and order["status"] in {"paid", "work"} and settings.refund_to_balance_enabled:
        refund_amount = float(order["price"] or 0)
        invoice = get_ton_invoice_by_order(order_id)
        amount_ton = float(invoice["amount_ton"] or 0) if invoice else 0.0
        if refund_amount > 0 and not get_refund_by_order(order_id):
            change_balance(int(order["user_id"]), refund_amount, f"Возврат TON-оплаты за заказ #{order_id} на баланс", order_id)
            create_refund_record(
                order_id=order_id,
                user_id=int(order["user_id"]),
                amount_kzt=refund_amount,
                amount_ton=amount_ton,
                method="ton_to_balance",
                status="done",
                note="Безопасный автовозврат TON-оплаты на внутренний баланс",
            )
            refund_text = (
                f"\n\n↩️ TON-оплата возвращена на внутренний баланс: <b>{money(refund_amount)}</b>."
                "\nПрямой on-chain возврат TON не выполняется, чтобы не хранить seed/private key в боте."
            )

    update_order_status(order_id, "cancelled")
    try:
        await callback.message.edit_text(format_order_for_admin(get_order(order_id)), reply_markup=admin_order_kb(order_id))
    except Exception:
        pass
    await callback.bot.send_message(
        int(order["user_id"]),
        f"❌ Ваш заказ <b>#{order_id}</b> отменён.{refund_text}\n\nЕсли нужна помощь — напишите в поддержку.",
    )
    await callback.answer("Заказ отменён")


@router.callback_query(F.data.startswith("admin_order_msg:"))
async def admin_order_message_button_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not can_manage_orders(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order_id = int(callback.data.split(":", 1)[1])
    order = get_order(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    await state.set_state(AdminOrderFSM.waiting_message)
    await state.update_data(order_id=order_id)
    await callback.message.answer(
        f"✉️ Напишите сообщение клиенту по заказу <b>#{order_id}</b>.\n"
        "Оно уйдёт клиенту от имени бота. Для отмены: /cancel"
    )
    await callback.answer()


@router.message(AdminOrderFSM.waiting_message)
async def admin_order_message_text_handler(message: Message, state: FSMContext) -> None:
    if not can_manage_orders(message.from_user.id):
        return

    data = await state.get_data()
    order_id = int(data.get("order_id") or 0)
    order = get_order(order_id)
    text_to_send = (message.html_text or message.text or "").strip()

    if not order:
        await state.clear()
        await message.answer("❌ Заказ не найден.", reply_markup=admin_panel_kb(admin_role(message.from_user.id)))
        return
    if len(text_to_send) < 2:
        await message.answer("Сообщение слишком короткое. Напишите текст для клиента.")
        return

    user_id = int(order["user_id"])
    try:
        await message.bot.send_message(
            user_id,
            f"✉️ <b>Сообщение по заказу #{order_id}</b>\n\n{text_to_send}",
            reply_markup=user_order_kb(order_id, str(order["status"])),
        )
        await message.answer(
            f"✅ Сообщение клиенту по заказу <b>#{order_id}</b> отправлено.",
            reply_markup=admin_order_kb(order_id),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cannot send order message to %s: %s", user_id, exc)
        await message.answer("❌ Не удалось отправить сообщение клиенту.", reply_markup=admin_order_kb(order_id))

    await state.clear()


@router.message(Command("order_reply"))
async def admin_order_reply_command_handler(message: Message) -> None:
    if not can_manage_orders(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Формат: <code>/order_reply ORDER_ID текст сообщения</code>")
        return

    try:
        order_id = int(parts[1])
    except ValueError:
        await message.answer("ORDER_ID должен быть числом.")
        return

    order = get_order(order_id)
    if not order:
        await message.answer("❌ Заказ не найден.")
        return

    await message.bot.send_message(
        int(order["user_id"]),
        f"✉️ <b>Сообщение по заказу #{order_id}</b>\n\n{safe(parts[2])}",
        reply_markup=user_order_kb(order_id, str(order["status"])),
    )
    await message.answer(f"✅ Сообщение по заказу <b>#{order_id}</b> отправлено.", reply_markup=admin_order_kb(order_id))


@router.callback_query(F.data == "admin_create_promo")
async def admin_create_promo_disabled_handler(callback: CallbackQuery) -> None:
    if not can_manage_settings(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer("Промокоды отключены", show_alert=True)

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not can_manage_settings(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminBroadcastFSM.waiting_text)
    await callback.message.answer("Введите текст рассылки. Для отмены: /cancel")
    await callback.answer()


@router.message(AdminBroadcastFSM.waiting_text)
async def admin_broadcast_text_handler(message: Message, state: FSMContext) -> None:
    if not can_manage_settings(message.from_user.id):
        return
    text = message.html_text or message.text or ""
    users = get_users()
    sent = 0
    failed = 0
    for user in users:
        try:
            await message.bot.send_message(int(user["user_id"]), text)
            sent += 1
            await asyncio.sleep(0.04)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.warning("Broadcast failed for %s: %s", user["user_id"], exc)
    await state.clear()
    await message.answer(f"✅ Рассылка завершена.\nОтправлено: {sent}\nОшибок: {failed}", reply_markup=admin_panel_kb(admin_role(message.from_user.id)))


@router.message(Command("balance_add"))
async def admin_balance_add_handler(message: Message) -> None:
    if not can_manage_settings(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    parts = (message.text or "").split(maxsplit=3)
    if len(parts) < 3:
        await message.answer("Формат: <code>/balance_add USER_ID SUM комментарий</code>")
        return
    try:
        user_id = int(parts[1])
        amount = float(parts[2].replace(",", "."))
    except ValueError:
        await message.answer("USER_ID и SUM должны быть числами.")
        return
    reason = parts[3] if len(parts) >= 4 else "Ручное изменение баланса админом"
    new_balance = change_balance(user_id, amount, reason)
    await message.answer(f"✅ Баланс изменён. Новый баланс пользователя {user_id}: <b>{money(new_balance)}</b>")
    try:
        await message.bot.send_message(user_id, f"💰 Баланс изменён на <b>{money(amount)}</b>.\nНовый баланс: <b>{money(new_balance)}</b>")
    except Exception:
        pass


@router.message(Command("reply"))
async def admin_reply_handler(message: Message) -> None:
    if not can_manage_support(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Формат: <code>/reply USER_ID текст ответа</code>")
        return
    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("USER_ID должен быть числом.")
        return
    await message.bot.send_message(user_id, f"📞 Ответ поддержки:\n\n{safe(parts[2])}")
    await message.answer("✅ Ответ отправлен.")


@router.callback_query(F.data.startswith("review:"))
async def review_handler(callback: CallbackQuery) -> None:
    _, order_id_raw, rating_raw = callback.data.split(":", 2)
    order_id = int(order_id_raw)
    rating = int(rating_raw)
    order = get_order(order_id)
    if not order or int(order["user_id"]) != callback.from_user.id:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    ok, msg = create_review(order_id, callback.from_user.id, rating)
    await callback.message.answer(f"⭐ {safe(msg)}")
    if ok:
        await notify_admins(
            callback.bot,
            f"⭐ <b>Новый отзыв</b>\n\n"
            f"Заказ: <b>#{order_id}</b>\n"
            f"Клиент: {user_mention(order['username'], int(order['user_id']))}\n"
            f"Оценка: <b>{rating}/5</b>",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("review_skip:"))
async def review_skip_handler(callback: CallbackQuery) -> None:
    await callback.answer("Хорошо", show_alert=False)
    await callback.message.answer("Оценку можно не оставлять. Спасибо за покупку!", reply_markup=back_menu_kb())


# =========================
# FALLBACK
# =========================


@router.message()
async def fallback_handler(message: Message) -> None:
    upsert_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    await message.answer("Выберите действие в меню или используйте /menu.", reply_markup=bottom_menu_kb())


# =========================
# TON AUTO PAYMENT HELPERS
# =========================

async def create_ton_payment_order(
    bot: Bot,
    user_id: int,
    username: str | None,
    category: str,
    product: str,
    details: str,
    price: float,
    target_message: Message,
    state: FSMContext | None = None,
) -> None:
    if price <= 0:
        await target_message.answer(
            "❌ Для автоматической TON-оплаты у товара должна быть фиксированная цена.\n"
            "Этот раздел пока оформляется через заявку.",
            reply_markup=back_menu_kb(),
        )
        return

    if not ton_is_configured():
        await target_message.answer(
            "❌ TON-оплата пока не настроена.\n\n"
            "В Railway нужно добавить TON_WALLET, TON_API_KEY и TON_RATE_KZT.",
            reply_markup=back_menu_kb(),
        )
        return

    order_id = create_order(
        user_id=user_id,
        username=username,
        category=category,
        product=product,
        details=details,
        price=price,
        payment_method="TON",
        status="waiting_ton",
        currency=user_currency(user_id),
        display_amount=kzt_to_currency(price, user_currency(user_id)),
    )
    current_rate = get_ton_rate_kzt()
    amount_ton = kzt_to_ton(price)
    comment = ton_invoice_comment(order_id, user_id)
    expires_at = (datetime.now() + timedelta(minutes=settings.ton_invoice_ttl_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    create_ton_invoice(order_id, user_id, price, amount_ton, comment, expires_at=expires_at)

    if state:
        await state.clear()

    await target_message.answer(
        f"💎 <b>TON-оплата заказа #{order_id}</b>\n\n"
        f"📦 Товар: <b>{safe(product)}</b>\n"
        f"💵 Сумма: <b>{money_multi(price)}</b>\n"
        f"💎 К оплате: <b>{amount_ton:g} TON</b>\n"
        f"📈 Курс: <b>1 TON ≈ {format_money(current_rate, 'KZT')} / {format_money(current_rate, 'RUB')}</b>\n\n"
        f"Отправьте ровно или больше <b>{amount_ton:g} TON</b> на адрес:\n"
        f"<code>{safe(settings.ton_wallet)}</code>\n\n"
        f"Комментарий к платежу обязательно:\n"
        f"<code>{safe(comment)}</code>\n\n"
        f"Счёт действует <b>{settings.ton_invoice_ttl_minutes}</b> минут, до <code>{expires_at}</code>.\n\n"
        "После оплаты нажмите кнопку проверки. Бот также сам периодически проверяет оплату.",
        reply_markup=ton_invoice_kb(order_id),
    )


@router.callback_query(F.data.startswith("ton_no_comment:"))
async def ton_no_comment_handler(callback: CallbackQuery, state: FSMContext) -> None:
    order_id = int(callback.data.split(":", 1)[1])
    order = get_order(order_id)
    if not order or int(order["user_id"]) != callback.from_user.id:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    await state.set_state(NoCommentFSM.waiting_report)
    await state.update_data(order_id=order_id)
    await callback.message.answer(
        "⚠️ <b>Оплата без комментария</b>\n\n"
        "Напишите одним сообщением:\n"
        "1) сумму TON;\n"
        "2) примерное время оплаты;\n"
        "3) последние 4 символа адреса отправителя или пришлите скрин.\n\n"
        "Админ проверит вручную.",
        reply_markup=back_menu_kb(),
    )
    await callback.answer()


@router.message(NoCommentFSM.waiting_report)
async def no_comment_report_text_handler(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = int(data.get("order_id") or 0)
    text = (message.text or message.caption or "").strip()
    if len(text) < 3 and not message.photo:
        await message.answer("Напишите детали оплаты или отправьте скрин.")
        return
    report_id = create_no_comment_report(order_id, message.from_user.id, message.from_user.username, text or "Скрин оплаты без комментария")
    order = get_order(order_id)
    notice = (
        f"⚠️ <b>Оплата без комментария #{report_id}</b>\n\n"
        f"Заказ: <b>#{order_id}</b>\n"
        f"Клиент: {user_mention(message.from_user.username, message.from_user.id)}\n"
        f"User ID: <code>{message.from_user.id}</code>\n\n"
        f"Сообщение клиента:\n{safe(text or 'приложен скрин')}\n\n"
        "Проверьте вручную в Tonkeeper / TON Center."
    )
    await notify_admins(message.bot, notice, reply_markup=admin_order_kb(order_id) if order else None)
    if message.photo:
        for admin_id in admin_ids():
            try:
                await message.forward(admin_id)
            except Exception:
                pass
    await state.clear()
    await message.answer(
        "✅ Заявка на ручную проверку отправлена администратору.\n"
        "Как только платёж проверят, вам ответят в боте.",
        reply_markup=user_order_kb(order_id, str(order["status"])) if order else back_menu_kb(),
    )


async def process_ton_paid_order(bot: Bot, order_id: int, tx_hash: str, amount_ton: float) -> bool:
    order = get_order(order_id)
    if not order or order["status"] != "waiting_ton":
        return False

    mark_ton_invoice_paid(order_id, tx_hash, amount_ton)

    if order["category"] == "top_up":
        change_balance(int(order["user_id"]), float(order["price"] or 0), f"TON пополнение по заявке #{order_id}", order_id)
        update_order_status(order_id, "done")
        try:
            await bot.send_message(
                int(order["user_id"]),
                f"✅ TON-оплата найдена. Баланс пополнен на <b>{money_multi(float(order['price'] or 0))}</b>.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cannot notify topup user %s: %s", order["user_id"], exc)
        await notify_admins(bot, f"💎 TON-пополнение #{order_id} оплачено автоматически.")
        return True

    update_order_status(order_id, "paid")
    paid_order = get_order(order_id)

    try:
        await bot.send_message(
            int(order["user_id"]),
            f"✅ TON-оплата по заказу <b>#{order_id}</b> найдена.\n\n"
            "Заказ оплачен и передан в обработку.",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cannot notify user %s: %s", order["user_id"], exc)

    if paid_order:
        await notify_admins(
            bot,
            "💎 <b>Заказ оплачен через TON автоматически</b>\n\n" + format_order_for_admin(paid_order),
            reply_markup=admin_order_kb(order_id),
        )
    return True


async def check_ton_invoice(bot: Bot, order_id: int) -> bool:
    invoice = get_ton_invoice_by_order(order_id)
    if not invoice or invoice["status"] != "pending":
        return False
    expires_at = invoice["expires_at"] if "expires_at" in invoice.keys() else None
    if expires_at:
        try:
            if datetime.strptime(str(expires_at), "%Y-%m-%d %H:%M:%S") < datetime.now():
                expire_ton_invoice(order_id)
                update_order_status(order_id, "expired")
                return False
        except Exception:
            pass
    tx = await asyncio.to_thread(find_ton_payment, invoice["comment"], float(invoice["amount_ton"]))
    if not tx:
        return False
    return await process_ton_paid_order(bot, order_id, str(tx["hash"]), float(tx["amount_ton"]))


async def ton_auto_checker(bot: Bot) -> None:
    while True:
        try:
            for invoice in list_pending_ton_invoices(limit=50):
                await check_ton_invoice(bot, int(invoice["order_id"]))
        except Exception as exc:  # noqa: BLE001
            logger.warning("TON checker error: %s", exc)
        await asyncio.sleep(45)


@router.callback_query(StateFilter(OrderFSM.waiting_payment), F.data == "pay:ton")
async def pay_ton_handler(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await create_ton_payment_order(
        bot=callback.bot,
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        category=data.get("category", "order"),
        product=data.get("product", "Заявка"),
        details=data.get("details", ""),
        price=float(data.get("price", 0) or 0),
        target_message=callback.message,
        state=state,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ton_check:"))
async def ton_check_handler(callback: CallbackQuery) -> None:
    order_id = int(callback.data.split(":", 1)[1])
    order = get_order(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    if int(order["user_id"]) != callback.from_user.id and not is_admin(callback.from_user.id):
        await callback.answer("Это не ваш заказ", show_alert=True)
        return
    if order["status"] != "waiting_ton":
        await callback.answer("Заказ уже не ожидает TON оплату", show_alert=True)
        return

    ok = await check_ton_invoice(callback.bot, order_id)
    if ok:
        await callback.message.answer(f"✅ Оплата заказа #{order_id} найдена.", reply_markup=back_menu_kb())
        await callback.answer("Оплата найдена")
    else:
        await callback.answer("Платёж пока не найден. Проверьте сумму и комментарий.", show_alert=True)


async def auto_backup_task(bot: Bot) -> None:
    while True:
        try:
            now_dt = datetime.now()
            target = now_dt.replace(hour=settings.auto_backup_hour, minute=0, second=0, microsecond=0)
            if target <= now_dt:
                target += timedelta(days=1)
            await asyncio.sleep((target - now_dt).total_seconds())
            if os.path.exists(settings.db_path):
                for admin_id in admin_ids():
                    try:
                        await bot.send_document(
                            admin_id,
                            FSInputFile(settings.db_path, filename=f"gamepay_auto_backup_{datetime.now().strftime('%Y%m%d')}.db"),
                            caption="💾 Автобэкап базы GamePay",
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Auto backup failed for %s: %s", admin_id, exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Auto backup task error: %s", exc)
            await asyncio.sleep(3600)


async def main() -> None:
    if not settings.bot_token:
        raise RuntimeError("Не указан BOT_TOKEN в .env")

    init_db()
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    if ton_is_configured():
        asyncio.create_task(ton_auto_checker(bot))
        logger.info("TON auto checker started")
    else:
        logger.warning("TON auto payments are not configured")

    if settings.auto_backup_enabled:
        asyncio.create_task(auto_backup_task(bot))
        logger.info("Auto backup task started")

    logger.info("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
