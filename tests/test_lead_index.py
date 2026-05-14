from app.lead_index import lead_id_for, lead_key_for


def test_lead_key_for_is_stable() -> None:
    assert lead_key_for("1:2") == lead_key_for("1:2")


def test_lead_key_for_is_short() -> None:
    assert len(lead_key_for("1:2")) == 12


def test_lead_id_for_uses_source_or_unknown() -> None:
    assert lead_id_for(123, 5) == "123:5"
    assert lead_id_for(None, 5) == "unknown:5"
