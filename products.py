from __future__ import annotations

# Цены можно менять прямо здесь. Если цена 0 — бот создаёт заявку "по договорённости".
STARS_PACKAGES = {
    "50": 85,
    "100": 165,
    "500": 800,
    "1000": 1550,
}

PREMIUM_PACKAGES = {
    "3": 1290,
    "6": 1790,
    "12": 2990,
}

PUBG_PACKAGES = {
    "60": 120,
    "325": 590,
    "660": 1150,
    "1800": 2990,
}

TOP_UP_AMOUNTS = [500, 1000, 2500, 5000]

CUSTOM_PRODUCTS = {
    "sell_stars": {
        "title": "💳 Продать звёзды",
        "prompt": "Напишите количество Stars, которое хотите продать, и ваш Telegram @username.\n\nПример: 500 Stars, @username",
    },
    "rent_nft": {
        "title": "⏰ Аренда NFT",
        "prompt": "Напишите NFT/ссылку, срок аренды и ваш Telegram @username.\n\nПример: NFT Premium badge, 7 дней, @username",
    },
    "buy_nft": {
        "title": "🎁 Купить NFT",
        "prompt": "Напишите название/ссылку NFT, бюджет и получателя.\n\nПример: NFT Gift #123, бюджет 50 TON, @username",
    },
    "buy_gift": {
        "title": "🧸 Купить обычный подарок",
        "prompt": "Напишите подарок, получателя и ваш комментарий.\n\nПример: Teddy Bear, получатель @username",
    },
    "buy_ton": {
        "title": "💎 Купить TON",
        "prompt": "Напишите сумму TON и адрес кошелька.\n\nПример: 2 TON, EQ...",
    },
}
