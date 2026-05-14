from __future__ import annotations

import logging
from html import escape
from typing import Any

from aiohttp import web

SETTINGS_KEY = web.AppKey("settings", object)
STATE_KEY = web.AppKey("state", object)

from app.crm_storage import get_stats as get_crm_stats, load_crm
from app.leads_storage import count_leads, get_all_leads
from app.source_discovery import load_candidates

logger = logging.getLogger(__name__)


def _status_counts(settings: Any) -> dict[str, int]:
    crm_stats = get_crm_stats(settings.crm_file)
    total = count_leads(settings.leads_file)
    implicit_new = max(0, total - crm_stats.get("total", 0))
    return {
        "total_leads": total,
        "new": crm_stats.get("new", 0) + implicit_new,
        "in_work": crm_stats.get("in_work", 0),
        "processed": crm_stats.get("processed", 0),
        "no_target": crm_stats.get("no_target", 0),
    }


def build_stats(settings: Any, state: Any) -> dict[str, Any]:
    stats = _status_counts(settings)
    stats.update({
        "отсеяно дублей": getattr(state, "duplicate_count", 0),
        "обработано сообщений": getattr(state, "processed_count", 0),
        "найдено лидов": getattr(state, "matched_count", 0),
    })
    return stats


def _layout(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title>"
        "<style>body{font-family:Arial,sans-serif;margin:24px}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ddd;padding:6px;vertical-align:top}th{background:#f3f3f3}.muted{color:#666}</style>"
        "</head><body>" + body + "</body></html>"
    )


def render_index_html(settings: Any, state: Any, token: str = "") -> str:
    stats = build_stats(settings, state)
    suffix = f"?token={escape(token)}" if token else ""
    rows = "".join(f"<li>{escape(key)}: <b>{value}</b></li>" for key, value in stats.items())
    body = f"<h1>Панель Telegram-бота</h1><ul>{rows}</ul><p><a href='/leads{suffix}'>Лиды</a> · <a href='/sources{suffix}'>Источники</a></p>"
    return _layout("Dashboard", body)


def render_leads_html(settings: Any) -> str:
    crm = load_crm(settings.crm_file)
    rows = []
    for lead in get_all_leads(settings.leads_file):
        status = crm.get(lead.lead_id).status if crm.get(lead.lead_id) else "new"
        comment = crm.get(lead.lead_id).comment if crm.get(lead.lead_id) else ""
        rows.append(
            "<tr>"
            f"<td>{escape(lead.matched_at.strftime('%Y-%m-%d %H:%M'))}</td>"
            f"<td>{escape(status)}</td>"
            f"<td>{escape('@' + lead.sender_username if lead.sender_username else '')}</td>"
            f"<td>{escape(lead.source_title or '')}</td>"
            f"<td>{escape(str(lead.score if lead.score is not None else ''))}</td>"
            f"<td>{escape(' '.join(lead.text.split())[:200])}</td>"
            f"<td>{('<a href=' + repr(escape(lead.message_link)) + '>link</a>') if lead.message_link else ''}</td>"
            f"<td>{escape(comment or '')}</td>"
            "</tr>"
        )
    body = "<h1>Лиды</h1><table><tr><th>Дата</th><th>Статус</th><th>Username</th><th>Источник</th><th>Оценка</th><th>Текст</th><th>Ссылка</th><th>Комментарий</th></tr>" + "".join(rows) + "</table>"
    return _layout("Leads", body)


def render_sources_html(settings: Any) -> str:
    rows = []
    for candidate in load_candidates(settings.source_candidates_file):
        status = "подписан" if candidate.get("joined") else "пропущен" if candidate.get("skipped") else "нужно вручную" if candidate.get("manual_required") else "ошибка" if candidate.get("error") else "новый"
        rows.append(
            "<tr>"
            f"<td>{escape(str(candidate.get('title') or ''))}</td>"
            f"<td>{escape(str(candidate.get('username') or ''))}</td>"
            f"<td>{escape(status)}</td>"
            "</tr>"
        )
    body = "<h1>Источники</h1><table><tr><th>Название</th><th>Username</th><th>Статус</th></tr>" + "".join(rows) + "</table>"
    return _layout("Sources", body)


def _authorized(request: web.Request, settings: Any) -> bool:
    token = getattr(settings, "web_dashboard_token", "")
    return not token or request.query.get("token") == token


@web.middleware
async def _token_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    settings = request.app[SETTINGS_KEY]
    if not _authorized(request, settings):
        return web.Response(status=401, text="Unauthorized")
    return await handler(request)


def create_web_app(settings: Any, state: Any) -> web.Application:
    app = web.Application(middlewares=[_token_middleware])
    app[SETTINGS_KEY] = settings
    app[STATE_KEY] = state

    async def index(request: web.Request) -> web.Response:
        return web.Response(text=render_index_html(settings, state, request.query.get("token", "")), content_type="text/html")

    async def leads(request: web.Request) -> web.Response:
        return web.Response(text=render_leads_html(settings), content_type="text/html")

    async def sources(request: web.Request) -> web.Response:
        return web.Response(text=render_sources_html(settings), content_type="text/html")

    async def api_stats(request: web.Request) -> web.Response:
        return web.json_response(build_stats(settings, state))

    app.router.add_get("/", index)
    app.router.add_get("/leads", leads)
    app.router.add_get("/sources", sources)
    app.router.add_get("/api/stats", api_stats)
    return app


async def start_web_dashboard(settings: Any, state: Any) -> web.AppRunner:
    host = getattr(settings, "web_dashboard_host", "127.0.0.1")
    if not getattr(settings, "web_dashboard_token", "") and host != "127.0.0.1":
        logger.warning("WEB_DASHBOARD_TOKEN is empty; binding dashboard to 127.0.0.1 for safety")
        host = "127.0.0.1"
    elif not getattr(settings, "web_dashboard_token", ""):
        logger.warning("WEB_DASHBOARD_TOKEN is empty; dashboard is local-only")
    runner = web.AppRunner(create_web_app(settings, state))
    await runner.setup()
    site = web.TCPSite(runner, host, settings.web_dashboard_port)
    await site.start()
    logger.info("Web dashboard started at http://%s:%s", host, settings.web_dashboard_port)
    return runner
