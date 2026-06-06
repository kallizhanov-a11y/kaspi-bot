import os
import asyncio
import aiohttp
from datetime import datetime, date, timedelta
import calendar
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot, Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# === НАСТРОЙКИ ===
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID", "769342417")
KASPI_TOKEN = os.environ.get("KASPI_TOKEN")
TIMEZONE = pytz.timezone("Asia/Almaty")
KASPI_API_URL = "https://kaspi.kz/shop/api/v2"

KEYBOARD = ReplyKeyboardMarkup([
    ["📊 Сегодня", "📅 Неделя"],
    ["🗓 Месяц", "❓ Помощь"],
], resize_keyboard=True)


async def get_orders(start_dt, end_dt):
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
            async with session.get(f"{KASPI_API_URL}/orders/", headers=headers, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"Kaspi API ошибка {resp.status}: {text}")
                data = await resp.json()
                orders = data.get("data", [])
                all_orders.extend(orders)
                total = data.get("meta", {}).get("total", 0)
                page_size = data.get("meta", {}).get("pageSize", 100)
                if (page + 1) * page_size >= total:
                    break
                page += 1
    return all_orders


def analyze_orders(orders):
    stats = {"total": len(orders), "my_delivery": 0, "express": 0, "zamler": 0, "other": 0, "total_sum": 0}
    for order in orders:
        attrs = order.get("attributes", {})
        delivery_mode = attrs.get("deliveryMode", "")
        courier = attrs.get("courier", {}) or {}
        courier_name = courier.get("name", "").lower() if courier else ""
        stats["total_sum"] += attrs.get("totalPrice", 0)
        if "zamler" in courier_name or "замлер" in courier_name:
            stats["zamler"] += 1
        elif delivery_mode == "DELIVERY_EXPRESS":
            stats["express"] += 1
        elif delivery_mode in ("DELIVERY_LOCAL", "DELIVERY"):
            stats["my_delivery"] += 1
        else:
            stats["other"] += 1
    return stats


def format_daily(stats):
    today_str = datetime.now(TIMEZONE).strftime("%d.%m.%Y")
    return f"""📊 *Отчёт за {today_str}*

━━━━━━━━━━━━━━━━━
📦 Всего заказов: *{stats['total']}*
💰 Сумма: *{stats['total_sum']:,.0f} ₸*
━━━━━━━━━━━━━━━━━

🚚 *Моя доставка:* {stats['my_delivery']} зак.
⚡ *Экспресс:* {stats['express']} зак.
🛵 *Замлер:* {stats['zamler']} зак.
📦 *Прочее:* {stats['other']} зак."""


def format_weekly(stats, week_start, week_end):
    s = week_start.strftime("%d.%m")
    e = week_end.strftime("%d.%m.%Y")
    avg = stats['total_sum'] / 7 if stats['total'] > 0 else 0
    avg_order = stats['total_sum'] / stats['total'] if stats['total'] > 0 else 0
    return f"""📅 *Неделя {s} — {e}*

━━━━━━━━━━━━━━━━━
📦 Всего заказов: *{stats['total']}*
💰 Выручка: *{stats['total_sum']:,.0f} ₸*
📈 В среднем/день: *{avg:,.0f} ₸*
🧾 Средний чек: *{avg_order:,.0f} ₸*
━━━━━━━━━━━━━━━━━

🚚 *Моя доставка:* {stats['my_delivery']} зак.
⚡ *Экспресс:* {stats['express']} зак.
🛵 *Замлер:* {stats['zamler']} зак.
📦 *Прочее:* {stats['other']} зак."""


def format_monthly(stats, month_name, year):
    days = stats.get('days', 30)
    avg = stats['total_sum'] / days if stats['total'] > 0 else 0
    avg_order = stats['total_sum'] / stats['total'] if stats['total'] > 0 else 0
    return f"""🗓 *{month_name} {year}*

━━━━━━━━━━━━━━━━━
📦 Всего заказов: *{stats['total']}*
💰 Выручка: *{stats['total_sum']:,.0f} ₸*
📈 В среднем/день: *{avg:,.0f} ₸*
🧾 Средний чек: *{avg_order:,.0f} ₸*
━━━━━━━━━━━━━━━━━

🚚 *Моя доставка:* {stats['my_delivery']} зак.
⚡ *Экспресс:* {stats['express']} зак.
🛵 *Замлер:* {stats['zamler']} зак.
📦 *Прочее:* {stats['other']} зак."""


# === ОБРАБОТЧИКИ КОМАНД ===

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот отчётов Kaspi магазина.\n\nВыберите что показать:",
        reply_markup=KEYBOARD,
    )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Загружаю данные...")
    try:
        now = datetime.now(TIMEZONE)
        start_dt = TIMEZONE.localize(datetime(now.year, now.month, now.day, 0, 0, 0))
        end_dt = TIMEZONE.localize(datetime(now.year, now.month, now.day, 23, 59, 59))
        orders = await get_orders(start_dt, end_dt)
        stats = analyze_orders(orders)
        await update.message.reply_text(format_daily(stats), parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=KEYBOARD)


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Загружаю данные за неделю...")
    try:
        now = datetime.now(TIMEZONE)
        week_start = now - timedelta(days=now.weekday())
        week_end = now
        start_dt = TIMEZONE.localize(datetime(week_start.year, week_start.month, week_start.day, 0, 0, 0))
        end_dt = TIMEZONE.localize(datetime(week_end.year, week_end.month, week_end.day, 23, 59, 59))
        orders = await get_orders(start_dt, end_dt)
        stats = analyze_orders(orders)
        await update.message.reply_text(format_weekly(stats, week_start, week_end), parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=KEYBOARD)


async def cmd_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Загружаю данные за месяц...")
    try:
        now = datetime.now(TIMEZONE)
        first_day = now.replace(day=1)
        start_dt = TIMEZONE.localize(datetime(first_day.year, first_day.month, 1, 0, 0, 0))
        end_dt = TIMEZONE.localize(datetime(now.year, now.month, now.day, 23, 59, 59))
        month_names = {1:"Январь",2:"Февраль",3:"Март",4:"Апрель",5:"Май",6:"Июнь",
                       7:"Июль",8:"Август",9:"Сентябрь",10:"Октябрь",11:"Ноябрь",12:"Декабрь"}
        orders = await get_orders(start_dt, end_dt)
        stats = analyze_orders(orders)
        stats['days'] = now.day
        await update.message.reply_text(format_monthly(stats, month_names[now.month], now.year), parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=KEYBOARD)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Команды бота:*\n\n"
        "📊 *Сегодня* — заказы за сегодня\n"
        "📅 *Неделя* — заказы с начала недели\n"
        "🗓 *Месяц* — заказы с начала месяца\n\n"
        "⏰ *Автоматические отчёты:*\n"
        "• Каждый день в 20:00\n"
        "• Каждый понедельник в 09:00\n"
        "• 1-го числа каждого месяца в 09:00",
        parse_mode="Markdown",
        reply_markup=KEYBOARD,
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "Сегодня" in text:
        await cmd_today(update, context)
    elif "Неделя" in text:
        await cmd_week(update, context)
    elif "Месяц" in text:
        await cmd_month(update, context)
    elif "Помощь" in text:
        await cmd_help(update, context)


# === АВТОМАТИЧЕСКИЕ ОТЧЁТЫ ===

async def auto_daily(bot):
    try:
        now = datetime.now(TIMEZONE)
        start_dt = TIMEZONE.localize(datetime(now.year, now.month, now.day, 0, 0, 0))
        end_dt = TIMEZONE.localize(datetime(now.year, now.month, now.day, 23, 59, 59))
        orders = await get_orders(start_dt, end_dt)
        stats = analyze_orders(orders)
        await bot.send_message(chat_id=CHAT_ID, text=format_daily(stats), parse_mode="Markdown")
    except Exception as e:
        await bot.send_message(chat_id=CHAT_ID, text=f"❌ Ошибка авто-отчёта: {e}")


async def auto_weekly(bot):
    try:
        now = datetime.now(TIMEZONE)
        week_end = now - timedelta(days=1)
        week_start = week_end - timedelta(days=6)
        start_dt = TIMEZONE.localize(datetime(week_start.year, week_start.month, week_start.day, 0, 0, 0))
        end_dt = TIMEZONE.localize(datetime(week_end.year, week_end.month, week_end.day, 23, 59, 59))
        orders = await get_orders(start_dt, end_dt)
        stats = analyze_orders(orders)
        await bot.send_message(chat_id=CHAT_ID, text=format_weekly(stats, week_start, week_end), parse_mode="Markdown")
    except Exception as e:
        await bot.send_message(chat_id=CHAT_ID, text=f"❌ Ошибка авто-отчёта: {e}")


async def auto_monthly(bot):
    try:
        now = datetime.now(TIMEZONE)
        first_day = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
        last_day = now.replace(day=1) - timedelta(days=1)
        start_dt = TIMEZONE.localize(datetime(first_day.year, first_day.month, 1, 0, 0, 0))
        end_dt = TIMEZONE.localize(datetime(last_day.year, last_day.month, last_day.day, 23, 59, 59))
        month_names = {1:"Январь",2:"Февраль",3:"Март",4:"Апрель",5:"Май",6:"Июнь",
                       7:"Июль",8:"Август",9:"Сентябрь",10:"Октябрь",11:"Ноябрь",12:"Декабрь"}
        orders = await get_orders(start_dt, end_dt)
        stats = analyze_orders(orders)
        stats['days'] = calendar.monthrange(first_day.year, first_day.month)[1]
        await bot.send_message(chat_id=CHAT_ID, text=format_monthly(stats, month_names[first_day.month], first_day.year), parse_mode="Markdown")
    except Exception as e:
        await bot.send_message(chat_id=CHAT_ID, text=f"❌ Ошибка авто-отчёта: {e}")


async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("month", cmd_month))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(
        chat_id=CHAT_ID,
        text="✅ Бот запущен! Теперь можно запросить отчёт в любое время через кнопки.",
    )

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(auto_daily, "cron", hour=20, minute=0, args=[bot])
    scheduler.add_job(auto_weekly, "cron", day_of_week="mon", hour=9, minute=0, args=[bot])
    scheduler.add_job(auto_monthly, "cron", day=1, hour=9, minute=0, args=[bot])
    scheduler.start()

    print("Бот запущен с интерактивными кнопками.")
    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
