# Parser_TG_Bot

Базовый Python-проект Telegram lead parser bot для поиска потенциальных заявок в доступных Telegram-чатах и каналах.

## Что делает проект

Приложение использует:

- **Telethon user session** — читает сообщения из чатов/каналов, доступных Telegram-аккаунту пользователя.
- **Telegram Bot API через aiogram 3.x** — отправляет уведомления администратору в личный чат или группу.
- **Простые ключевые фразы** — на первом этапе без ML/NLP, только поиск подстроки без учёта регистра.
- **Локальный JSON-файл** — хранит уже обработанные сообщения, чтобы не отправлять дубли.

Примеры ключевых фраз по умолчанию:

- `как понизить налоги`
- `понизить налоги`
- `снизить налоги`
- `оптимизация налогов`

## Требования

- Python 3.11+
- Telegram API ID и API HASH с <https://my.telegram.org>
- Telegram-бот, созданный через `@BotFather`

## Установка

1. Склонируйте репозиторий и перейдите в папку проекта.

2. Создайте виртуальное окружение.

   Windows PowerShell:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   Linux/macOS:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Установите зависимости.

   ```bash
   pip install -r requirements.txt
   ```

## Настройка .env

Скопируйте пример настроек:

```bash
cp .env.example .env
```

На Windows можно выполнить:

```powershell
Copy-Item .env.example .env
```

Заполните `.env`:

```env
API_ID=123456
API_HASH=your_api_hash
SESSION_NAME=parser_account
BOT_TOKEN=123456:bot_token
ADMIN_CHAT_ID=123456789
SOURCE_CHATS=
KEYWORDS=как понизить налоги,понизить налоги,снизить налоги,оптимизация налогов
DEDUP_FILE=data/processed_messages.json
```

### Пояснение настроек

- `API_ID` и `API_HASH` — данные приложения Telegram с <https://my.telegram.org>.
- `SESSION_NAME` — имя локального файла Telethon-сессии без расширения. Например, `parser_account` создаст файл `parser_account.session`.
- `BOT_TOKEN` — токен бота от `@BotFather`.
- `ADMIN_CHAT_ID` — ID чата, куда отправлять уведомления.
- `SOURCE_CHATS` — список usernames, ссылок или ID через запятую. Если оставить пустым, приложение будет слушать все доступные входящие сообщения/каналы, которые Telethon отдаёт через `events.NewMessage`.
- `KEYWORDS` — ключевые фразы через запятую.
- `DEDUP_FILE` — путь к JSON-файлу с обработанными сообщениями.

## Как получить ADMIN_CHAT_ID

Самый простой способ:

1. Напишите любое сообщение вашему боту.
2. Откройте в браузере:

   ```text
   https://api.telegram.org/bot<BOT_TOKEN>/getUpdates
   ```

3. Найдите поле `chat.id` в ответе JSON и укажите это значение в `ADMIN_CHAT_ID`.

Если уведомления должны приходить в группу, добавьте бота в группу и отправьте туда сообщение. Затем снова вызовите `getUpdates` и возьмите `chat.id` группы.

## Создание Telethon user session

Перед первым запуском парсера создайте user session:

```bash
python create_session.py
```

Скрипт попросит телефон, код Telegram и, если включена двухфакторная защита, пароль. После успешной авторизации будет создан файл вида `parser_account.session`.

Скрипт выводит только безопасную информацию об аккаунте: ID, имя и username. `API_HASH`, `BOT_TOKEN` и session string не печатаются.

## Запуск парсера

```bash
python -m app.main
```

Для быстрого теста можно оставить `SOURCE_CHATS` пустым. Тогда приложение будет слушать все доступные события, которые получает Telethon user session.

Когда в доступном чате появится сообщение с одной из ключевых фраз, администратору придёт уведомление через Telegram-бота.

## Архитектура

```text
.
├── create_session.py      # создание Telethon user session
├── app
│   ├── config.py          # загрузка и валидация настроек из .env
│   ├── filters.py         # проверка текста по ключевым фразам
│   ├── main.py            # основной запуск Telethon client и обработчиков
│   ├── models.py          # модель найденной заявки
│   ├── notifier.py        # отправка уведомлений через aiogram Bot
│   └── storage.py         # JSON-дедупликация обработанных сообщений
```

## Безопасность

Нельзя публиковать или коммитить:

- `.env`
- `*.session`
- `*.session-journal`
- содержимое папки `data/`

Эти файлы добавлены в `.gitignore`. В коде нет хардкода секретов, а логи не печатают `API_HASH`, `BOT_TOKEN` или session string.

## Критерии готовности

- `python create_session.py` запускается и создаёт Telethon session.
- `python -m app.main` запускает парсер.
- Сообщение с ключевой фразой в доступном чате приводит к уведомлению администратору.
- Секреты не попадают в git.
- Код проходит проверку на синтаксические ошибки.
