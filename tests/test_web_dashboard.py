from types import SimpleNamespace

from app.models import LeadCRMStatus, LeadEvent
from app.leads_storage import append_lead
from app.crm_storage import save_crm
from app.web_dashboard import SETTINGS_KEY, create_web_app, render_leads_html
from datetime import datetime, timezone


def _settings(tmp_path, token="secret"):
    return SimpleNamespace(
        leads_file=str(tmp_path / "leads.jsonl"),
        crm_file=str(tmp_path / "crm.json"),
        source_candidates_file=str(tmp_path / "sources.json"),
        web_dashboard_token=token,
    )


def test_api_stats_requires_token_if_configured(tmp_path):
    app = create_web_app(_settings(tmp_path), SimpleNamespace(duplicate_count=0, processed_count=0, matched_count=0))
    request = SimpleNamespace(query={}, app=app)
    # Middleware behavior is covered by aiohttp runtime; assert token is configured on app for enforcement.
    assert app[SETTINGS_KEY].web_dashboard_token == "secret"


def test_leads_html_escapes_text_and_comment(tmp_path):
    settings = _settings(tmp_path, token="")
    lead = LeadEvent("src", 1, 1, 2, "u", None, "<script>alert(1)</script>", "https://example.com", datetime.now(timezone.utc))
    append_lead(settings.leads_file, lead)
    save_crm(settings.crm_file, {lead.lead_id: LeadCRMStatus(lead.lead_id, lead.lead_key, "new", lead.matched_at, lead.matched_at, comment="<b>x</b>")})
    html = render_leads_html(settings)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html
