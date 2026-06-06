import os
import asyncio
import aiohttp
from datetime import datetime, timedelta
import calendar
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID", "769342417")
KASPI_TOKEN = os.environ.get("KASPI_TOKEN")
TIMEZONE = pytz.timezone("Asia/Almaty")

# Правильный URL Kaspi API
KASPI_API_URL = "https://kaspi.kz/shop/api/v2"

KEYBOARD = ReplyKeyboardMarkup([
    ["📊 Сегодня", "📅 Неделя"],
    ["🗓 Месяц", "❓ Помощь"],
], resize_keyboard=True)


async def get_orders_by_status(statuses, start_dt, end_dt):
    """Получаем заказы по статусу и дате"""
    headers = {
        "Content-Type": "application/json",
        "X-Auth-Token": KASPI_TOKEN,
    }

    all_orders = []

    async with aiohttp.ClientSession() as session:
        for status in statuses:
            page = 0
            while True:
                params = {
                    "page[number]": page,
                    "page[size]": 100,
                    "filter[orders][state]": status,
                    "filter[orders][creationDate][$ge]": int(start_dt.timestamp()) * 1000,
                    "filter[orders][creationDate][$le]": int(end_dt.timestamp()) * 1000,
                }
                async with session.get(
                    f"{KASPI_API_URL}/orders/",
                    headers=headers,
                    params=params
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise Exception(f"Kaspi API ошибка {resp.status}: {text[:200]}")
                    data = await resp.json()
                    orders = data.get("data", [])
                    all_orders.extend(orders)
                    total = data.get("meta", {}).get("total", 0)
                    page_size = data.get("meta", {}).get("pageSize", 100)
                    if (page + 1) * page_size >= total:
                        break
                    page += 1

    return all_orders


def get_delivery_type(order):
    # Замлер и Kaspi доставка = одно и то же
    attrs = order.get("attributes", {})
    delivery_mode = attrs.get("deliveryMode", "")
    courier = attrs.get("courier", {}) or {}
    courier_name = courier.get("name", "").lower() if courier else ""

    if delivery_mode == "DELIVERY_EXPRESS":
        return "express"
    elif delivery_mode in ("DELIVERY_LOCAL", "DELIVERY"):
        return "my_delivery"
    else:
        return "kaspi"  # Замлер / Kaspi доставка


def analyze(orders):
    stats = {
        "total": len(orders),
        "express": 0,
        "my_delivery": 0,
        "kaspi": 0,
        "total_sum": 0,
    }
    for order in orders:
        attrs = order.get("attributes", {})
        stats["total_sum"] += attrs.get("totalPrice", 0)
        dtype = get_delivery_type(order)
        stats[dtype] = stats.get(dtype, 0) + 1
    return stats


def day_range(dt=None):
    now = dt or datetime.now(TIMEZONE)
    start = TIMEZONE.localize(datetime(now.year, now.month, now.day, 0, 0, 0))
    end = TIMEZONE.localize(datetime(now.year, now.month, now.day, 23, 59, 59))
    return start, end


def format_report(stats, title, period_str):
    avg_order = stats['total_sum'] / stats['total'] if stats['total'] > 0 else 0
    return f"""{title} *{period_str}*

━━━━━━━━━━━━━━━━━
📦 Передано на доставку: *{stats['total']} шт.*
💰 Сумма заказов: *{stats['total_sum']:,.0f} ₸*
🧾 Средний чек: *{avg_order:,.0f} ₸*
━━━━━━━━━━━━━━━━━

⚡ *Экспресс:* {stats['express']} шт.
🚚 *Моя доставка:* {stats['my_delivery']} шт.
📦 *Kaspi/Замлер:* {stats['kaspi']} шт."""


# Статусы заказов переданных на доставку
DELIVERY_STATUSES = ["PICKUP_WAITING", "DELIVERING", "COMPLETED"]


async def cmd_start(update, context):
    await update.message.reply_text(
        "👋 Привет! Я показываю сколько заказов передано на доставку.\nВыберите период:",
        reply_markup=KEYBOARD,
    )


async def cmd_today(update, context):
    await update.message.reply_text("⏳ Загружаю данные...")
    try:
        start, end = day_range()
        orders = await get_orders_by_status(DELIVERY_STATUSES, start, end)
        stats = analyze(orders)
        today_str = datetime.now(TIMEZONE).strftime("%d.%m.%Y")
        await update.message.reply_text(
            format_report(stats, "📊", today_str),
            parse_mode="Markdown", reply_markup=KEYBOARD
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=KEYBOARD)


async def cmd_week(update, context):
    await update.message.reply_text("⏳ Загружаю данные за неделю...")
    try:
        now = datetime.now(TIMEZONE)
        week_start = now - timedelta(days=now.weekday())
        start = TIMEZONE.localize(datetime(week_start.year, week_start.month, week_start.day, 0, 0, 0))
        end = TIMEZONE.localize(datetime(now.year, now.month, now.day, 23, 59, 59))
        orders = await get_orders_by_status(DELIVERY_STATUSES, start, end)
        stats = analyze(orders)
        period = f"{week_start.strftime('%d.%m')} — {now.strftime('%d.%m.%Y')}"
        await update.message.reply_text(
            format_report(stats, "📅", period),
            parse_mode="Markdown", reply_markup=KEYBOARD
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=KEYBOARD)


async def cmd_month(update, context):
    await update.message.reply_text("⏳ Загружаю данные за месяц...")
    try:
        now = datetime.now(TIMEZONE)
        start = TIMEZONE.localize(datetime(now.year, now.month, 1, 0, 0, 0))
        end = TIMEZONE.localize(datetime(now.year, now.month, now.day, 23, 59, 59))
        month_names = {1:"Январь",2:"Февраль",3:"Март",4:"Апрель",5:"Май",6:"Июнь",
                       7:"Июль",8:"Август",9:"Сентябрь",10:"Октябрь",11:"Ноябрь",12:"Декабрь"}
        orders = await get_orders_by_status(DELIVERY_STATUSES, start, end)
        stats = analyze(orders)
        period = f"{month_names[now.month]} {now.year}"
        await update.message.reply_text(
            format_report(stats, "🗓", period),
            parse_mode="Markdown", reply_markup=KEYBOARD
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=KEYBOARD)


async def cmd_help(update, context):
    await update.message.reply_text(
        "📋 *Бот считает заказы переданные на доставку*\n\n"
        "📊 *Сегодня* — сколько передали сегодня\n"
        "📅 *Неделя* — с начала этой недели\n"
        "🗓 *Месяц* — с начала этого месяца\n\n"
        "⏰ Автоотчёт приходит каждый день в *20:00*",
        parse_mode="Markdown", reply_markup=KEYBOARD,
    )


async def handle_message(update, context):
    text = update.message.text
    if "Сегодня" in text:
        await cmd_today(update, context)
    elif "Неделя" in text:
        await cmd_week(update, context)
    elif "Месяц" in text:
        await cmd_month(update, context)
    elif "Помощь" in text:
        await cmd_help(update, context)


async def auto_daily(app):
    try:
        start, end = day_range()
        orders = await get_orders_by_status(DELIVERY_STATUSES, start, end)
        stats = analyze(orders)
        today_str = datetime.now(TIMEZONE).strftime("%d.%m.%Y")
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text=format_report(stats, "📊 Ежедневный отчёт", today_str),
            parse_mode="Markdown"
        )
    except Exception as e:
        await app.bot.send_message(chat_id=CHAT_ID, text=f"❌ Ошибка авто-отчёта: {e}")


async def post_init(app):
    await app.bot.send_message(
        chat_id=CHAT_ID,
        text="✅ Бот запущен! Отчёт каждый день в 20:00.\nНажмите кнопку чтобы посмотреть сейчас:",
        reply_markup=KEYBOARD,
    )
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(auto_daily, "cron", hour=20, minute=0, args=[app])
    scheduler.start()


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("month", cmd_month))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
