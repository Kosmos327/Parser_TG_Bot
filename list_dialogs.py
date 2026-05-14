from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from telethon import TelegramClient, errors, utils

from app.config import load_settings
from app.dialogs import dialog_info_from_entity, format_dialog_cli_item, is_source_dialog_allowed
from app.source_search_settings import load_source_search_settings

DEFAULT_LIMIT = 200


def _session_file_exists(session_name: str) -> bool:
    session_path = Path(session_name).expanduser()
    candidates = [session_path]
    if session_path.suffix != ".session":
        candidates.append(session_path.with_suffix(session_path.suffix + ".session") if session_path.suffix else Path(f"{session_path}.session"))
    return any(candidate.exists() for candidate in candidates)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Показать Telegram-чаты/каналы, доступные текущей Telegram-сессии."
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Сколько диалогов вывести (по умолчанию {DEFAULT_LIMIT}).")
    parser.add_argument("--all", action="store_true", help="Показать все диалоги, игнорируя настройки поиска источников.")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    if args.limit < 1:
        print("Ошибка: --limit должен быть положительным числом.")
        return 2

    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"Ошибка настроек: {exc}")
        return 2

    if not _session_file_exists(settings.session_name):
        print("Session-файл не найден: сначала выполните python create_session.py")
        return 1

    client = TelegramClient(settings.session_name, settings.api_id, settings.api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print("Telegram-сессия не авторизована: сначала выполните python create_session.py")
            return 1

        print(f"Первые {args.limit} диалогов, доступных текущей Telegram-сессии:\n")
        source_settings = load_source_search_settings(settings.source_search_settings_file, settings)
        printed = 0
        iter_limit = args.limit if args.all else args.limit * 5
        async for dialog in client.iter_dialogs(limit=iter_limit):
            if printed >= args.limit:
                break
            if not args.all and not is_source_dialog_allowed(dialog, source_settings=source_settings):
                continue
            entity = dialog.entity
            info = dialog_info_from_entity(entity, peer_id=utils.get_peer_id(entity))
            print(format_dialog_cli_item(info, printed + 1))
            print()
            printed += 1

        if printed == 0:
            print("Диалоги не найдены. Проверьте, что Telegram-аккаунт подписан на нужные чаты/каналы.")

        print("Username удобнее для списка источников SOURCE_CHATS; если username нет, используйте ID.")
        print("Для .env можно указать несколько источников через запятую:")
        print("SOURCE_CHATS=@business_chat,-1001234567890")
        return 0
    except errors.AuthKeyError:
        print("Ошибка авторизации Telegram-сессии: пересоздайте session через python create_session.py")
        return 1
    except errors.RPCError as exc:
        print(f"Ошибка Telegram API при получении диалогов: {type(exc).__name__}: {exc}")
        return 1
    finally:
        await client.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
