import os
import asyncio
import aiohttp
from datetime import datetime, date
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

# === НАСТРОЙКИ ===
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID", "769342417")
KASPI_TOKEN = os.environ.get("KASPI_TOKEN")
TIMEZONE = pytz.timezone("Asia/Almaty")

KASPI_API_URL = "https://kaspi.kz/shop/api/v2"

DELIVERY_NAMES = {
    "KASPI_DELIVERY": "🚚 Моя доставка",
    "EXPRESS": "⚡ Экспресс",
    "SELF_PICKUP": "🏪 Самовывоз",
}

ZAMLER_STATUSES = ["PICKUP_WAITING", "DELIVERING"]


async def get_orders_today():
    """Получаем заказы за сегодня через Kaspi API"""
    today = date.today()
    # Временные метки начала и конца дня (Алматы)
    start_dt = TIMEZONE.localize(datetime(today.year, today.month, today.day, 0, 0, 0))
    end_dt = TIMEZONE.localize(datetime(today.year, today.month, today.day, 23, 59, 59))

    start_ts = int(start_dt.timestamp()) * 1000
    end_ts = int(end_dt.timestamp()) * 1000

    headers = {
        "Content-Type": "application/json",
        "X-Auth-Token": KASPI_TOKEN,
    }

    params = {
        "page[number]": 0,
        "page[size]": 100,
        "filter[orders][creationDate][$ge]": start_ts,
        "filter[orders][creationDate][$le]": end_ts,
        "filter[orders][state]": "APPROVED",
        "include[orders]": "deliveryAddress",
    }

    all_orders = []

    async with aiohttp.ClientSession() as session:
        page = 0
        while True:
            params["page[number]"] = page
            async with session.get(
                f"{KASPI_API_URL}/orders/",
                headers=headers,
                params=params,
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"Kaspi API ошибка {resp.status}: {text}")

                data = await resp.json()
                orders = data.get("data", [])
                all_orders.extend(orders)

                # Проверяем есть ли ещё страницы
                total = data.get("meta", {}).get("total", 0)
                page_size = data.get("meta", {}).get("pageSize", 100)
                if (page + 1) * page_size >= total:
                    break
                page += 1

    return all_orders


def analyze_orders(orders):
    """Анализируем заказы по типу доставки"""
    stats = {
        "total": len(orders),
        "my_delivery": 0,
        "express": 0,
        "zamler": 0,
        "other": 0,
        "total_sum": 0,
    }

    for order in orders:
        attrs = order.get("attributes", {})
        delivery_mode = attrs.get("deliveryMode", "")
        courier = attrs.get("courier", {}) or {}
        courier_name = courier.get("name", "").lower() if courier else ""

        # Сумма
        stats["total_sum"] += attrs.get("totalPrice", 0)

        # Категоризация
        if "zamler" in courier_name or "замлер" in courier_name:
            stats["zamler"] += 1
        elif delivery_mode == "DELIVERY_EXPRESS":
            stats["express"] += 1
        elif delivery_mode in ("DELIVERY_LOCAL", "DELIVERY"):
            stats["my_delivery"] += 1
        else:
            stats["other"] += 1

    return stats


def format_report(stats):
    """Формируем красивый отчёт"""
    today_str = datetime.now(TIMEZONE).strftime("%d.%m.%Y")

    report = f"""📊 *Отчёт за {today_str}*

━━━━━━━━━━━━━━━━━
📦 Всего заказов: *{stats['total']}*
💰 Общая сумма: *{stats['total_sum']:,.0f} ₸*
━━━━━━━━━━━━━━━━━

🚚 *Моя доставка:* {stats['my_delivery']} зак.
⚡ *Экспресс:* {stats['express']} зак.
🛵 *Замлер:* {stats['zamler']} зак.
📦 *Прочее:* {stats['other']} зак.

━━━━━━━━━━━━━━━━━
🕗 Отчёт сформирован в 20:00"""

    return report


async def send_daily_report():
    """Основная функция отправки отчёта"""
    bot = Bot(token=TELEGRAM_TOKEN)

    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text="⏳ Собираю данные по заказам...",
            parse_mode="Markdown",
        )

        orders = await get_orders_today()
        stats = analyze_orders(orders)
        report = format_report(stats)

        await bot.send_message(
            chat_id=CHAT_ID,
            text=report,
            parse_mode="Markdown",
        )

    except Exception as e:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=f"❌ Ошибка при получении данных:\n`{str(e)}`",
            parse_mode="Markdown",
        )


async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(
        chat_id=CHAT_ID,
        text="✅ Бот запущен! Отчёт будет приходить каждый день в 20:00 по Алматы.",
    )

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(send_daily_report, "cron", hour=20, minute=0)
    scheduler.start()

    print("Бот запущен. Отчёт каждый день в 20:00 по Алматы.")

    # Держим бота живым
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
