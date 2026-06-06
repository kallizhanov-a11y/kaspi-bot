# Kaspi Daily Report Bot

Бот отправляет ежедневный отчёт по заказам в 20:00 по Алматы.

## Переменные окружения (задать в Railway)

| Переменная | Описание |
|---|---|
| `TELEGRAM_TOKEN` | Токен бота от @BotFather |
| `CHAT_ID` | Ваш Telegram ID (769342417) |
| `KASPI_TOKEN` | Токен Kaspi магазина |

## Деплой на Railway

1. Создайте аккаунт на https://railway.app
2. New Project → Deploy from GitHub repo
3. Загрузите файлы в GitHub репозиторий
4. В Railway → Variables добавьте три переменные выше
5. Deploy!
