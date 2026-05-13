from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ParserState:
    enabled: bool = True
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    processed_count: int = 0
    matched_count: int = 0
    last_error: str | None = None

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False

    def status_text(self) -> str:
        status = "включен" if self.enabled else "выключен"
        last_error = self.last_error or "нет"
        started_at = self.started_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return (
            f"Статус парсера: {status}\n"
            f"Запущен: {started_at}\n"
            f"Обработано сообщений: {self.processed_count}\n"
            f"Найдено заявок: {self.matched_count}\n"
            f"Последняя ошибка: {last_error}"
        )
