# Reputation Bot

Telegram-бот для управления репутацией участников группы.

## Возможности

- **Иерархия прав:** команды доступны только владельцу группы, её администраторам и назначенным модераторам. Обычные участники игнорируются.
- **База пользователей:** добавление по `@username`, Telegram user ID или ответом на сообщение.
- **Изменение репутации:** упомяните бота и пользователя в одном сообщении — появится меню с инлайн-кнопками `+/-` со значениями 1, 5, 10, 20, 50, 100, 500.
- **Лимит:** репутация ограничена ±5000 баллов; значения сверх лимита обрезаются.
- **Постоянное хранилище:** PostgreSQL (`DATABASE_URL`) для продакшена или SQLite-файл для локальной разработки — переключается одной переменной окружения.
- **Мульти-группы:** один экземпляр бота поддерживает работу в нескольких группах; репутация изолирована по `chat_id`.

## Команды

| Команда                              | Кто может | Описание                                   |
|--------------------------------------|-----------|--------------------------------------------|
| `/start`, `/help`                    | все       | Справка                                    |
| `/add <@username \| ID>`             | админ     | Добавить пользователя в базу               |
| `/delete <@username \| ID>`          | админ     | Удалить пользователя                       |
| `/grant <@username \| ID>`           | владелец  | Выдать права модератора                    |
| `/revoke <@username \| ID>`          | владелец  | Отозвать права модератора                  |
| `/mods`                              | все       | Список модераторов                         |
| `/rep [@username \| ID]`             | все       | Посмотреть репутацию (по умолчанию — свою) |
| `/top [N]`                           | все       | Топ участников (по умолчанию 10, макс. 50) |
| Упоминание `@bot @user` (или reply)  | модератор | Меню с кнопками +/-                        |

«Админ» — владелец группы Telegram или её администратор. «Владелец» — создатель группы Telegram. Дополнительно можно указать `OWNER_ID` в переменных окружения — этот пользователь получает права владельца во всех группах, где есть бот.

## Запуск локально

Требования: Python 3.11+.

```bash
# 1. Установка
python -m venv .venv
source .venv/bin/activate
pip install -e .

# 2. Настройте .env
cp .env.example .env
# отредактируйте .env и впишите BOT_TOKEN от @BotFather

# 3. Запуск
export $(grep -v '^#' .env | xargs)
python -m reputation_bot
```

### Установите бота в группу

1. Получите токен у [@BotFather](https://t.me/BotFather) (`/newbot`).
2. Добавьте бота в вашу группу.
3. Сделайте бота администратором группы и **отключите режим конфиденциальности** (Group Privacy) в настройках бота у @BotFather — без этого бот не будет видеть упоминания других пользователей.
4. Команды можно зарегистрировать у @BotFather через `/setcommands`:
   ```
   start - Показать справку
   help - Показать справку
   add - Добавить пользователя в базу
   delete - Удалить пользователя из базы
   grant - Выдать права модератора
   revoke - Отозвать права модератора
   mods - Список модераторов
   rep - Посмотреть репутацию
   top - Топ по репутации
   ```

## Деплой

### Render.com (бесплатный 24/7 с UptimeRobot и Neon Postgres)

Проект содержит готовый `render.yaml` (Blueprint) и `Dockerfile`.

1. Создайте бесплатную базу на [Neon](https://neon.tech) (Sign in with GitHub):
   - **New Project** → Postgres 16, любой регион.
   - На странице проекта откройте **Connection Details** → скопируйте строку **Pooled connection** (длинная `postgresql://...?sslmode=require`).
2. Зарегистрируйтесь на https://render.com — без карты, через GitHub или email.
3. **New** → **Blueprint** → подключите этот публичный репозиторий.
4. В настройках сервиса задайте секреты:
   - `BOT_TOKEN` — токен от @BotFather.
   - `DATABASE_URL` — строка подключения Neon (включая `?sslmode=require`).
5. Дождитесь деплоя. Health-check на `/healthz` должен стать зелёным; `WEBHOOK_URL` автоматически вычисляется из `RENDER_EXTERNAL_URL`.
6. Чтобы сервис не засыпал (free-tier Render засыпает через 15 минут простоя):
   - Зарегистрируйтесь на https://uptimerobot.com (бесплатно).
   - **Add new monitor** → HTTP(S) → URL: `https://<имя-сервиса>.onrender.com/healthz` → интервал 5 минут.

Вся репутация и список модераторов хранятся в Neon — данные переживают любые перезапуски и редеплои Render.

Если `DATABASE_URL` не задан, бот падает обратно на локальный SQLite (`DB_PATH`, по умолчанию `reputation.db`), который на бесплатном тарифе Render обнуляется при каждом редеплое — используйте только для тестов.

### Docker (свой VPS)

```bash
docker build -t reputation-bot .

# Вариант 1: с Postgres (Neon / любой managed Postgres)
docker run -d \
    --name reputation-bot \
    -e BOT_TOKEN=YOUR_TOKEN \
    -e DATABASE_URL=postgresql://user:pass@host/db?sslmode=require \
    --restart unless-stopped \
    reputation-bot:latest python -m reputation_bot

# Вариант 2: с локальным SQLite на volume
docker run -d \
    --name reputation-bot \
    -e BOT_TOKEN=YOUR_TOKEN \
    -v $(pwd)/data:/data \
    -e DB_PATH=/data/reputation.db \
    --restart unless-stopped \
    reputation-bot:latest python -m reputation_bot
```

(Polling-режим, не требует публичного URL.)

### Fly.io

```bash
fly launch --no-deploy
fly secrets set BOT_TOKEN=YOUR_TOKEN
fly volumes create reputation_data --size 1
fly deploy
```

## Разработка

```bash
pip install -e ".[dev]"
ruff check .
mypy src
pytest
```

## Лицензия

MIT
