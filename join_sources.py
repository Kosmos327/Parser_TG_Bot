from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from telethon import TelegramClient

from app.config import load_settings
from app.source_discovery import parse_sources_text
from app.source_joiner import join_sources_limited, public_username_sources


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely join a limited batch of public Telegram sources.")
    parser.add_argument("sources", nargs="*", help="@username or t.me links. If empty, read --file or stdin.")
    parser.add_argument("--file", help="Read sources from a TXT list or JSON source candidates file.")
    parser.add_argument("--max-join", type=int, help="Override JOIN_BATCH_LIMIT for this run.")
    parser.add_argument("--delay", type=int, help="Override JOIN_DELAY_SECONDS for this run.")
    parser.add_argument("--dry-run", action="store_true", help="Print normalized sources without joining.")
    return parser.parse_args()


def _sources_from_file(path: str) -> str:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if file_path.suffix.lower() != ".json":
        return text

    data: Any = json.loads(text)
    if not isinstance(data, list):
        return ""
    values: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        username = item.get("username") or item.get("source_chats_value")
        if username:
            values.append(str(username))
    return "\n".join(values)


def _read_raw_sources(args: argparse.Namespace) -> str:
    if args.sources:
        return "\n".join(args.sources)
    if args.file:
        return _sources_from_file(args.file)
    return sys.stdin.read()


async def main() -> int:
    args = parse_args()
    settings = load_settings()
    max_join = args.max_join if args.max_join is not None else settings.join_batch_limit
    delay = args.delay if args.delay is not None else settings.join_delay_seconds
    sources = parse_sources_text(_read_raw_sources(args))

    if args.dry_run:
        normalized = public_username_sources(sources, max_join)
        print("Dry run. Sources to join:")
        for source in normalized:
            print(source)
        print(f"Total: {len(normalized)}")
        return 0

    client = TelegramClient(settings.session_name, settings.api_id, settings.api_hash)
    await client.start()
    try:
        result = await join_sources_limited(client, sources, delay, max_join)
        print(result)
        return 0
    finally:
        await client.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
