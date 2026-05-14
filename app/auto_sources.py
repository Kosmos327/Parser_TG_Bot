from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.source_discovery import export_candidates_txt, filter_joinable_candidates, load_candidates, mark_candidate_status, merge_candidates, save_candidates, search_sources
from app.source_search_settings import load_source_search_settings
from app.source_joiner import join_sources_limited

logger = logging.getLogger(__name__)


def _is_connected(client: Any) -> bool:
    try:
        return bool(client and client.is_connected())
    except Exception:
        return False


def _candidate_value(candidate: dict[str, Any]) -> str | None:
    return candidate.get("source_chats_value") or (f"@{candidate.get('username')}" if candidate.get("username") else None)


async def run_auto_source_discovery_once(settings: Any, state: Any, client: Any, bot: Any | None = None) -> str:
    if state.auto_source_discovery_in_progress:
        return "Автопоиск источников уже выполняется."
    state.auto_source_discovery_in_progress = True
    state.auto_source_discovery_last_run = datetime.now(timezone.utc)
    try:
        if not _is_connected(client):
            raise RuntimeError("Telegram-сессия недоступна или не подключена")
        existing = load_candidates(settings.source_candidates_file)
        source_settings = load_source_search_settings(settings.source_search_settings_file, settings)
        found = await search_sources(client, settings.auto_source_discovery_queries, settings.auto_source_discovery_limit, source_settings)
        merged = merge_candidates(existing, found)
        save_candidates(merged, settings.source_candidates_file)
        export_candidates_txt(merged, settings.source_export_file)
        new_count = max(0, len(merged) - len(existing))
        report = f"Автопоиск источников завершён. Найдено новых: {new_count}. Всего найденных источников: {len(merged)}."

        if settings.auto_source_auto_join:
            joinable = filter_joinable_candidates(merged)
            values = [value for candidate in joinable if (value := _candidate_value(candidate))]

            async def status_callback(source: str, status: str) -> None:
                mapped = "manual_required" if status in {"manual_required", "floodwait"} else status
                mark_candidate_status(settings.source_candidates_file, source, mapped)

            result = await join_sources_limited(
                client,
                values,
                settings.join_delay_seconds,
                settings.auto_source_join_limit,
                status_callback=status_callback,
            )
            report += f" Автоподписка: успешно {len(result['joined'])}, ошибки {len(result['failed'])}, ручные {len(result['manual_required'])}."
        state.auto_source_discovery_last_report = report
        if bot is not None:
            await bot.send_message(settings.admin_chat_id, report)
        return report
    except Exception as exc:
        state.last_error = str(exc)
        report = f"Ошибка автопоиска источников: {exc}"
        state.auto_source_discovery_last_report = report
        logger.exception("auto source discovery failed")
        if bot is not None:
            await bot.send_message(settings.admin_chat_id, report)
        return report
    finally:
        state.auto_source_discovery_in_progress = False


async def auto_source_discovery_loop(settings: Any, state: Any, client: Any, bot: Any) -> None:
    while True:
        await run_auto_source_discovery_once(settings, state, client, bot)
        await asyncio.sleep(max(1, settings.auto_source_discovery_interval_hours) * 3600)
