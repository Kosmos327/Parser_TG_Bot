from __future__ import annotations

import argparse
import asyncio

from telethon import TelegramClient

from app.config import load_settings
from app.source_discovery import parse_sources_text
from app.source_joiner import join_sources_limited


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely join a limited batch of public Telegram sources.")
    parser.add_argument("sources", nargs="*", help="@username or t.me links. If empty, read stdin.")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    settings = load_settings()
    raw = "\n".join(args.sources) if args.sources else input("Sources: ")
    sources = parse_sources_text(raw)
    client = TelegramClient(settings.session_name, settings.api_id, settings.api_hash)
    await client.start()
    try:
        result = await join_sources_limited(client, sources, settings.join_delay_seconds, settings.join_batch_limit)
        print(result)
        return 0
    finally:
        await client.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
