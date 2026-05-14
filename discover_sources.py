from __future__ import annotations

import argparse
import asyncio

from telethon import TelegramClient

from app.config import load_settings
from app.source_discovery import export_candidates_txt, save_candidates, search_sources
from app.source_search_settings import load_source_search_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Найти новые Telegram-источники по словам/фразам.")
    parser.add_argument("queries", nargs="+", help="Слова или фразы для поиска.")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    settings = load_settings()
    client = TelegramClient(settings.session_name, settings.api_id, settings.api_hash)
    await client.start()
    try:
        source_settings = load_source_search_settings(settings.source_search_settings_file, settings)
        candidates = await search_sources(client, args.queries, settings.source_search_limit, source_settings)
        save_candidates(candidates, settings.source_candidates_file)
        export_candidates_txt(candidates, settings.source_export_file)
        print(f"Найдено источников: {len(candidates)}. TXT-файл: {settings.source_export_file}")
        return 0
    finally:
        await client.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
