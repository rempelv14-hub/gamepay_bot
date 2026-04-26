# GamePay Bot v10 Refund + Roles + Auto TON Rate

Telegram-бот-магазин цифровых товаров с TON-оплатой, заказами, поддержкой и расширенной админкой.

## Что добавлено в v10

1. Безопасный автоматический возврат TON-оплаты на внутренний баланс при отмене заказа.
2. Роли админов: владелец, менеджер, поддержка.
3. Автоматический курс TON/KZT с fallback на `TON_RATE_KZT`.
4. Команда `/ton_rate` для проверки текущего курса.
5. Экспорт таблицы `refunds` в CSV.
6. Всё из v9: статистика, цены через админку, включение товаров, рассылка, тикеты, FAQ, бэкап, отзывы.

## Файлы, которые нужно загрузить в GitHub

Обязательно заменить:

```text
bot.py
config.py
database.py
keyboards.py
states.py
.env.example
README.md
```

Остальные файлы должны остаться из прошлой версии:

```text
products.py
texts.py
ton_payments.py
requirements.txt
Dockerfile
```

## Railway Variables

Минимум:

```env
BOT_TOKEN=...
ADMIN_ID=...
SUPPORT_USERNAME=Coldri13
BOT_USERNAME=gamepay_shop_bot
CURRENCY_SYMBOL=₸
TON_WALLET=...
TON_API_KEY=...
TON_RATE_KZT=1200
TON_INVOICE_TTL_MINUTES=30
```

Для нескольких админов и ролей:

```env
ADMIN_IDS=123456789,987654321

# Владелец: всё может. Если OWNER_IDS пустой, ADMIN_ID/ADMIN_IDS считаются владельцами.
OWNER_IDS=123456789

# Менеджер: заказы, тикеты, статистика.
MANAGER_IDS=987654321

# Поддержка: только тикеты и ответы клиентам.
SUPPORT_IDS=777777777
```

Автоматический курс TON:

```env
TON_RATE_AUTO_ENABLED=1
TON_RATE_CACHE_MINUTES=15
TON_RATE_KZT=1200
```

Безопасный возврат:

```env
REFUND_TO_BALANCE_ENABLED=1
```

Автобэкап:

```env
AUTO_BACKUP_ENABLED=1
AUTO_BACKUP_HOUR=9
```

## Запуск локально

```bash
pip install -r requirements.txt
python bot.py
```

## Railway Start Command

```bash
python bot.py
```
