from __future__ import annotations

import asyncio
import html
import logging
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message

from config import settings
from database import (
    activate_promocode,
    change_balance,
    create_order,
    create_promocode,
    create_support_ticket,
    count_user_support_tickets,
    close_support_ticket,
    get_support_ticket,
    answer_support_ticket,
    get_order,
    get_stats,
    get_user,
    get_user_orders,
    get_user_activity_stats,
    get_users,
    init_db,
    list_orders,
    mark_reward_paid,
    top_clients,
    create_ton_invoice,
    get_ton_invoice_by_order,
    list_pending_ton_invoices,
    mark_ton_invoice_paid,
    update_order_status,
    upsert_user,
)
from keyboards import (
    admin_order_kb,
    admin_panel_kb,
    calculator_choice_kb,
    calculator_result_kb,
    back_menu_kb,
    bottom_menu_kb,
    main_menu_kb,
    money,
    payment_choice_kb,
    premium_kb,
    profile_kb,
    pubg_packages_kb,
    stars_packages_kb,
    support_panel_kb,
    admin_ticket_kb,
    top_up_kb,
    ton_invoice_kb,
)
from products import CUSTOM_PRODUCTS, PREMIUM_PACKAGES, PUBG_PACKAGES, STARS_PACKAGES
from states import AdminBroadcastFSM, AdminPromoFSM, AdminTicketFSM, CalculatorFSM, OrderFSM, PromoFSM, PubgFSM, SupportFSM, TopUpFSM
from texts import INFO_TEXT, MENU_TEXT
from ton_payments import find_ton_payment, kzt_to_ton, ton_invoice_comment, ton_is_configured

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("shop_bot")

router = Router()


# =========================
# HELPERS
# =========================


def is_admin(user_id: int) -> bool:
    return settings.admin_id != 0 and user_id == settings.admin_id


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


def format_order_for_admin(order: dict[str, Any] | Any) -> str:
    username = order["username"] or "без username"
    return (
        f"<b>📦 Заказ #{order['id']}</b>\n\n"
        f"👤 Клиент: {user_mention(username if username != 'без username' else None, int(order['user_id']))}\n"
        f"🆔 User ID: <code>{order['user_id']}</code>\n\n"
        f"📂 Категория: <b>{safe(order['category'])}</b>\n"
        f"📦 Товар: <b>{safe(order['product'])}</b>\n"
        f"💵 Цена/сумма: <b>{money(float(order['price'] or 0))}</b>\n"
        f"💳 Оплата: <b>{safe(order['payment_method'])}</b>\n"
        f"📝 Детали: {safe(order['details'])}\n\n"
        f"📌 Статус: <b>{order_status_ru(order['status'])}</b>\n"
        f"🕒 Создан: <code>{order['created_at']}</code>"
    )


def format_order_for_user(order: dict[str, Any] | Any) -> str:
    return (
        f"<b>Заказ #{order['id']}</b>\n"
        f"Товар: {safe(order['product'])}\n"
        f"Цена/сумма: {money(float(order['price'] or 0))}\n"
        f"Статус: {order_status_ru(order['status'])}\n"
        f"Дата: <code>{order['created_at']}</code>"
    )


async def send_main_menu(message: Message) -> None:
    await message.answer(MENU_TEXT, reply_markup=main_menu_kb())


async def notify_admin_order(bot: Bot, order_id: int) -> None:
    if settings.admin_id == 0:
        return
    order = get_order(order_id)
    if not order:
        return
    await bot.send_message(settings.admin_id, format_order_for_admin(order), reply_markup=admin_order_kb(order_id))


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
                f"Нужно: <b>{money(price)}</b>\n"
                f"Ваш баланс: <b>{money(balance)}</b>\n\n"
                f"Пополните баланс или создайте заявку с ручной оплатой.",
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
        )
        change_balance(callback.from_user.id, -price, f"Оплата заказа #{order_id}", order_id)
    else:
        order_id = create_order(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            category=category,
            product=product,
            details=details,
            price=price,
            payment_method="manual",
            status="new",
        )

    await notify_admin_order(callback.bot, order_id)
    await state.clear()

    if payment_method == "balance" and price > 0:
        payment_text = "Оплата списана с вашего баланса."
    else:
        payment_text = (
            "Администратор проверит заявку.\n\n"
            "Для ручной оплаты используйте реквизиты:\n"
            f"<blockquote>{safe(settings.payment_details)}</blockquote>"
        )

    await callback.message.answer(
        f"✅ Заявка <b>#{order_id}</b> создана.\n\n"
        f"📦 {safe(product)}\n"
        f"💵 {money(price)}\n\n"
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

    upsert_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
        ref_by=ref_by,
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
        f"Баланс: <b>{money(balance)}</b>\n"
        f"Заказов всего: <b>{activity['orders_count']}</b>\n"
        f"Выполнено: <b>{activity['done_orders']}</b>\n"
        f"Покупок на сумму: <b>{money(activity['total_spent'])}</b>\n"
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


@router.callback_query(F.data == "my_orders")
async def my_orders_handler(callback: CallbackQuery) -> None:
    orders = get_user_orders(callback.from_user.id, limit=7)
    if not orders:
        await callback.message.answer("У вас пока нет заказов.", reply_markup=back_menu_kb())
        await callback.answer()
        return
    text = "<b>📦 Ваши последние заказы</b>\n\n" + "\n\n".join(format_order_for_user(o) for o in orders)
    await callback.message.answer(text, reply_markup=back_menu_kb())
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

    if kind == "stars":
        price = STARS_PACKAGES[code]
        product = f"Telegram Stars — {code} Stars"
        prompt = "Введите @username получателя или ссылку на профиль Telegram."
        category = "Telegram Stars"
    elif kind == "premium":
        price = PREMIUM_PACKAGES[code]
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
        f"Цена: <b>{money(price)}</b>\n\n"
        f"{prompt}",
        reply_markup=back_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("custom:"))
async def custom_product_handler(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
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
            "Введите сумму заказа в тенге, чтобы бот создал TON-оплату.\n"
            "Пример: <code>2500</code>",
            reply_markup=back_menu_kb(),
        )
        return

    await state.set_state(OrderFSM.waiting_payment)
    await message.answer(
        f"<b>Проверьте заявку</b>\n\n"
        f"📦 Товар: <b>{safe(product)}</b>\n"
        f"💵 Цена: <b>{money(price)}</b>\n"
        f"📝 Детали: {safe(text)}\n\n"
        f"Выберите способ оформления:",
        reply_markup=payment_choice_kb(price),
    )


@router.message(OrderFSM.waiting_custom_price)
async def order_custom_price_handler(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").replace(" ", "").replace(",", ".")
    try:
        price = float(raw)
    except ValueError:
        await message.answer("Введите сумму цифрами. Пример: 2500")
        return

    if price <= 0:
        await message.answer("Сумма должна быть больше 0.")
        return

    data = await state.get_data()
    await state.update_data(price=price)
    await state.set_state(OrderFSM.waiting_payment)

    product = data.get("product", "Заявка")
    details = data.get("details", "")
    await message.answer(
        f"<b>Проверьте заявку</b>\n\n"
        f"📦 Товар: <b>{safe(product)}</b>\n"
        f"💵 Цена: <b>{money(price)}</b>\n"
        f"📝 Детали: {safe(details)}\n\n"
        "Выберите способ оформления:",
        reply_markup=payment_choice_kb(price),
    )


@router.callback_query(StateFilter(OrderFSM.waiting_payment), F.data == "pay:balance")
async def pay_balance_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await finish_order_from_state(callback, state, "balance")


@router.callback_query(StateFilter(OrderFSM.waiting_payment), F.data == "pay:manual")
async def pay_manual_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await finish_order_from_state(callback, state, "manual")


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
    price = PUBG_PACKAGES[uc]
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
        f"💵 Цена: <b>{money(price)}</b>\n\n"
        f"Выберите способ оформления:",
        reply_markup=payment_choice_kb(price),
    )
    await callback.answer()


# =========================
# TOP UP / PROMO / SUPPORT
# =========================


@router.callback_query(F.data == "top_up_balance")
async def top_up_handler(callback: CallbackQuery) -> None:
    await callback.message.edit_text("💰 Выберите сумму пополнения:", reply_markup=top_up_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("topup_amount:"))
async def topup_amount_handler(callback: CallbackQuery, state: FSMContext) -> None:
    amount = float(callback.data.split(":", 1)[1])
    await create_ton_payment_order(
        bot=callback.bot,
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        category="top_up",
        product="Пополнение баланса",
        details=f"TON-пополнение баланса на {money(amount)}",
        price=amount,
        target_message=callback.message,
        state=state,
    )
    await callback.answer()


@router.callback_query(F.data == "topup_custom")
async def topup_custom_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TopUpFSM.waiting_amount)
    await callback.message.answer("Введите сумму пополнения цифрами.\n\nПример: 1500")
    await callback.answer()


@router.message(TopUpFSM.waiting_amount)
async def topup_custom_amount_handler(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").replace(" ", "").replace(",", ".")
    try:
        amount = float(raw)
    except ValueError:
        await message.answer("Введите сумму цифрами. Пример: 1500")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше 0.")
        return
    await create_ton_payment_order(
        bot=message.bot,
        user_id=message.from_user.id,
        username=message.from_user.username,
        category="top_up",
        product="Пополнение баланса",
        details=f"TON-пополнение баланса на {money(amount)}",
        price=amount,
        target_message=message,
        state=state,
    )
@router.callback_query(F.data == "promo")
async def promo_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PromoFSM.waiting_code)
    await callback.message.answer("🎟 Введите промокод:", reply_markup=back_menu_kb())
    await callback.answer()


@router.message(PromoFSM.waiting_code)
async def promo_code_handler(message: Message, state: FSMContext) -> None:
    code = (message.text or "").strip()
    upsert_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    ok, result, amount = activate_promocode(code, message.from_user.id)
    await state.clear()
    if ok:
        await message.answer(f"✅ {safe(result)}", reply_markup=back_menu_kb())
    else:
        await message.answer(f"❌ {safe(result)}", reply_markup=back_menu_kb())


def support_panel_text(user_id: int) -> str:
    stats = count_user_support_tickets(user_id)
    active = stats.get("open", 0)
    total = stats.get("total", 0)
    status_line = (
        "✅ Вы можете создать новый тикет для обращения в поддержку."
        if active == 0
        else "⚠️ У вас уже есть активный тикет. Вы можете создать новый, если вопрос другой."
    )
    return (
        "<b>📞 Техническая поддержка</b>\n\n"
        "В этом разделе Вы можете создать тикет для связи с поддержкой.\n\n"
        "<b>📊 Статистика:</b>\n"
        f"• Активных тикетов: <b>{active}</b>\n"
        f"• Всего тикетов: <b>{total}</b>\n\n"
        f"{status_line}"
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
        "Например: что хотели купить, номер заказа, что не получилось или какую ошибку видите.",
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

    if settings.admin_id:
        await message.bot.send_message(
            settings.admin_id,
            f"<b>🆘 Новый тикет поддержки #{ticket_id}</b>\n\n"
            f"👤 Клиент: {user_mention(message.from_user.username, message.from_user.id)}\n"
            f"🆔 User ID: <code>{message.from_user.id}</code>\n"
            f"🔗 Username: @{safe(message.from_user.username) if message.from_user.username else 'не указан'}\n\n"
            f"<b>Жалоба / вопрос:</b>\n{safe(text)}\n\n"
            f"Ответить можно кнопкой ниже или командой:\n<code>/ticket_reply {ticket_id} ваш текст</code>",
            reply_markup=admin_ticket_kb(ticket_id),
        )

    await state.clear()
    await message.answer(
        f"✅ Тикет <b>#{ticket_id}</b> создан.\n\n"
        "Ваше сообщение отправлено администратору. Ожидайте ответа.",
        reply_markup=back_menu_kb(),
    )


@router.callback_query(F.data.startswith("admin_ticket_reply:"))
async def admin_ticket_reply_button_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    ticket_id = int(callback.data.split(":", 1)[1])
    ticket = get_support_ticket(ticket_id)
    if not ticket:
        await callback.answer("Тикет не найден", show_alert=True)
        return

    await state.set_state(AdminTicketFSM.waiting_reply)
    await state.update_data(ticket_id=ticket_id)
    await callback.message.answer(
        f"✉️ Введите ответ на тикет <b>#{ticket_id}</b> одним сообщением.\n\n"
        f"Клиент: {user_mention(ticket['username'], int(ticket['user_id']))}\n"
        f"Вопрос: {safe(ticket['message'])}\n\n"
        "Для отмены используйте /cancel"
    )
    await callback.answer()


@router.message(AdminTicketFSM.waiting_reply)
async def admin_ticket_reply_text_handler(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
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
        await message.answer("❌ Тикет не найден или уже удалён.")
        return

    user_id = int(ticket["user_id"])
    try:
        await message.bot.send_message(
            user_id,
            f"<b>📞 Ответ поддержки по тикету #{ticket_id}</b>\n\n"
            f"<b>Ваш вопрос:</b>\n{safe(ticket['message'])}\n\n"
            f"<b>Ответ администратора:</b>\n{safe(reply_text)}"
        )
        await message.answer(f"✅ Ответ по тикету <b>#{ticket_id}</b> отправлен клиенту.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send ticket reply to %s: %s", user_id, exc)
        await message.answer(
            f"⚠️ Ответ сохранён, но не удалось отправить клиенту. Возможно, клиент заблокировал бота.\n"
            f"Тикет: <b>#{ticket_id}</b>"
        )


@router.message(Command("ticket_reply"))
async def admin_ticket_reply_command_handler(message: Message) -> None:
    if not is_admin(message.from_user.id):
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
        await message.answer("❌ Тикет не найден.")
        return

    user_id = int(ticket["user_id"])
    try:
        await message.bot.send_message(
            user_id,
            f"<b>📞 Ответ поддержки по тикету #{ticket_id}</b>\n\n"
            f"<b>Ваш вопрос:</b>\n{safe(ticket['message'])}\n\n"
            f"<b>Ответ администратора:</b>\n{safe(reply_text)}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send ticket reply to %s: %s", user_id, exc)
        await message.answer("⚠️ Ответ сохранён, но не удалось отправить клиенту. Возможно, клиент заблокировал бота.")
        return

    await message.answer(f"✅ Ответ по тикету <b>#{ticket_id}</b> отправлен клиенту.")


@router.callback_query(F.data.startswith("admin_ticket_close:"))
async def admin_ticket_close_handler(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
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
        await callback.bot.send_message(int(ticket["user_id"]), f"✅ Ваш тикет поддержки <b>#{ticket_id}</b> закрыт.")
    except Exception:
        pass
    await callback.answer("Тикет закрыт")


@router.callback_query(F.data == "calculator")
async def calculator_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    lines = ["<b>🧮 Калькулятор цены</b>\n"]
    lines.append("Выберите, что хотите посчитать. Бот сам рассчитает сумму по текущему прайсу.\n")
    lines.append("<b>Готовые цены:</b>")
    lines.append("Stars: " + ", ".join([f"{amount} — {money(price)}" for amount, price in STARS_PACKAGES.items()]))
    lines.append("Premium: " + ", ".join([f"{months} мес. — {money(price)}" for months, price in PREMIUM_PACKAGES.items()]))
    lines.append("PUBG UC: " + ", ".join([f"{uc} — {money(price)}" for uc, price in PUBG_PACKAGES.items()]))
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
        price, note = estimate_package_price(STARS_PACKAGES, amount)
        title = f"⭐ {amount} Stars"
    elif kind == "uc":
        price, note = estimate_package_price(PUBG_PACKAGES, amount)
        title = f"🎮 {amount} UC"
    else:
        price, note = estimate_package_price(PREMIUM_PACKAGES, amount)
        title = f"👑 Premium на {amount} мес."
    await state.clear()
    await message.answer(
        f"<b>🧮 Расчёт</b>\n\n"
        f"Товар: <b>{safe(title)}</b>\n"
        f"Цена: <b>{money(price)}</b>\n"
        f"Тип расчёта: {safe(note)}\n\n"
        f"Для точного оформления нажмите кнопку ниже и выберите пакет.",
        reply_markup=calculator_result_kb(kind),
    )
@router.callback_query(F.data == "info")
async def info_handler(callback: CallbackQuery) -> None:
    await callback.message.answer(INFO_TEXT, reply_markup=back_menu_kb())
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
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    await message.answer("<b>🛠 Админ-панель</b>", reply_markup=admin_panel_kb())


@router.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    stats = get_stats()
    await callback.message.answer(
        "<b>📊 Статистика</b>\n\n"
        f"Пользователей: <b>{stats['users_count']}</b>\n"
        f"Всего заказов: <b>{stats['orders_count']}</b>\n"
        f"Активных заказов: <b>{stats['active_orders']}</b>\n"
        f"Открытых вопросов: <b>{stats['open_tickets']}</b>\n"
        f"Сумма выполненных заказов: <b>{money(float(stats['done_sum']))}</b>",
        reply_markup=admin_panel_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_orders")
async def admin_orders_handler(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    orders = list_orders(limit=10)
    if not orders:
        await callback.message.answer("Новых заказов нет.", reply_markup=admin_panel_kb())
        await callback.answer()
        return
    for order in orders:
        await callback.message.answer(format_order_for_admin(order), reply_markup=admin_order_kb(int(order["id"])))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_work:"))
async def admin_work_handler(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
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
    if not is_admin(callback.from_user.id):
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
        await callback.message.edit_text(format_order_for_admin(get_order(order_id)))
    except Exception:
        pass
    await callback.bot.send_message(
        int(order["user_id"]),
        f"✅ Ваш заказ <b>#{order_id}</b> выполнен.\n\nСпасибо за покупку!",
    )
    await callback.answer("Заказ выполнен")


@router.callback_query(F.data.startswith("admin_cancel:"))
async def admin_cancel_handler(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
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

    if order["payment_method"] == "balance" and order["status"] != "done":
        change_balance(int(order["user_id"]), float(order["price"] or 0), f"Возврат за отмену заказа #{order_id}", order_id)

    update_order_status(order_id, "cancelled")
    try:
        await callback.message.edit_text(format_order_for_admin(get_order(order_id)))
    except Exception:
        pass
    await callback.bot.send_message(
        int(order["user_id"]),
        f"❌ Ваш заказ <b>#{order_id}</b> отменён.\n\nЕсли нужна помощь — напишите в поддержку.",
    )
    await callback.answer("Заказ отменён")


@router.callback_query(F.data == "admin_create_promo")
async def admin_create_promo_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminPromoFSM.waiting_code)
    await callback.message.answer("Введите код промокода.\n\nПример: START100")
    await callback.answer()


@router.message(AdminPromoFSM.waiting_code)
async def admin_promo_code_handler(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    code = (message.text or "").strip().upper().replace(" ", "")
    if len(code) < 3:
        await message.answer("Код слишком короткий. Пример: START100")
        return
    await state.update_data(code=code)
    await state.set_state(AdminPromoFSM.waiting_amount)
    await message.answer("Введите сумму бонуса на баланс.\n\nПример: 100")


@router.message(AdminPromoFSM.waiting_amount)
async def admin_promo_amount_handler(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        amount = float((message.text or "").replace(",", "."))
    except ValueError:
        await message.answer("Введите сумму цифрами.")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше 0.")
        return
    await state.update_data(amount=amount)
    await state.set_state(AdminPromoFSM.waiting_limit)
    await message.answer("Введите лимит активаций.\n\nПример: 10")


@router.message(AdminPromoFSM.waiting_limit)
async def admin_promo_limit_handler(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        limit = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите лимит цифрами.")
        return
    if limit <= 0:
        await message.answer("Лимит должен быть больше 0.")
        return
    data = await state.get_data()
    create_promocode(data["code"], float(data["amount"]), limit)
    await state.clear()
    await message.answer(
        f"✅ Промокод создан:\n\n"
        f"Код: <code>{safe(data['code'])}</code>\n"
        f"Бонус: <b>{money(float(data['amount']))}</b>\n"
        f"Лимит: <b>{limit}</b>",
        reply_markup=admin_panel_kb(),
    )


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminBroadcastFSM.waiting_text)
    await callback.message.answer("Введите текст рассылки. Для отмены: /cancel")
    await callback.answer()


@router.message(AdminBroadcastFSM.waiting_text)
async def admin_broadcast_text_handler(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
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
    await message.answer(f"✅ Рассылка завершена.\nОтправлено: {sent}\nОшибок: {failed}", reply_markup=admin_panel_kb())


@router.message(Command("balance_add"))
async def admin_balance_add_handler(message: Message) -> None:
    if not is_admin(message.from_user.id):
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
    if not is_admin(message.from_user.id):
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
    )
    amount_ton = kzt_to_ton(price)
    comment = ton_invoice_comment(order_id, user_id)
    create_ton_invoice(order_id, user_id, price, amount_ton, comment)

    if state:
        await state.clear()

    await target_message.answer(
        f"💎 <b>TON-оплата заказа #{order_id}</b>\n\n"
        f"📦 Товар: <b>{safe(product)}</b>\n"
        f"💵 Сумма: <b>{money(price)}</b>\n"
        f"💎 К оплате: <b>{amount_ton:g} TON</b>\n\n"
        f"Отправьте ровно или больше <b>{amount_ton:g} TON</b> на адрес:\n"
        f"<code>{safe(settings.ton_wallet)}</code>\n\n"
        f"Комментарий к платежу обязательно:\n"
        f"<code>{safe(comment)}</code>\n\n"
        "После оплаты нажмите кнопку проверки. Бот также сам периодически проверяет оплату.",
        reply_markup=ton_invoice_kb(order_id),
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
                f"✅ TON-оплата найдена. Баланс пополнен на <b>{money(float(order['price'] or 0))}</b>.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cannot notify topup user %s: %s", order["user_id"], exc)
        if settings.admin_id:
            try:
                await bot.send_message(settings.admin_id, f"💎 TON-пополнение #{order_id} оплачено автоматически.")
            except Exception:
                pass
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

    if settings.admin_id and paid_order:
        await bot.send_message(
            settings.admin_id,
            "💎 <b>Заказ оплачен через TON автоматически</b>\n\n" + format_order_for_admin(paid_order),
            reply_markup=admin_order_kb(order_id),
        )
    return True


async def check_ton_invoice(bot: Bot, order_id: int) -> bool:
    invoice = get_ton_invoice_by_order(order_id)
    if not invoice or invoice["status"] != "pending":
        return False
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

    logger.info("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
