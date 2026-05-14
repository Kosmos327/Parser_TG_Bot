from __future__ import annotations

import argparse
import asyncio

from telethon import TelegramClient

from app.config import load_settings
from app.source_discovery import export_candidates_txt, save_candidates, search_sources


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find public Telegram source candidates by query.")
    parser.add_argument("queries", nargs="+", help="Search words/phrases.")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    settings = load_settings()
    client = TelegramClient(settings.session_name, settings.api_id, settings.api_hash)
    await client.start()
    try:
        candidates = await search_sources(client, args.queries, settings.source_search_limit)
        save_candidates(candidates, settings.source_candidates_file)
        export_candidates_txt(candidates, settings.source_export_file)
        print(f"Found {len(candidates)} candidates. Exported to {settings.source_export_file}")
        return 0
    finally:
        await client.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
