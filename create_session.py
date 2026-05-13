from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from telethon import TelegramClient


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Required environment variable {name} is not set or empty")
    return value


async def main() -> None:
    load_dotenv()

    api_id = int(_require_env("API_ID"))
    api_hash = _require_env("API_HASH")
    session_name = _require_env("SESSION_NAME")

    async with TelegramClient(session_name, api_id, api_hash) as client:
        me = await client.get_me()
        print("Telethon user session is ready.")
        print(f"User ID: {me.id}")
        print(f"First name: {me.first_name or ''}")
        print(f"Username: {me.username or ''}")


if __name__ == "__main__":
    asyncio.run(main())
