from types import SimpleNamespace

from app.services import calculate_lead_score


def test_score_is_transparent_and_capped():
    lead = SimpleNamespace(
        crm="HubSpot",
        confidence=0.85,
        evidence=[{"source": "https://example.com"}, {"source": "https://example.com/contato"}],
        contact_email="vendas@example.com",
        company_name="Example",
        sector="Varejo",
    )
    score, temperature, reasons = calculate_lead_score(lead)
    assert score == 90
    assert temperature == "hot"
    assert any("e-mail" in reason for reason in reasons)


def test_no_crm_is_cold_even_with_contact():
    lead = SimpleNamespace(
        crm=None,
        confidence=0,
        evidence=[],
        contact_email="contato@example.com",
        company_name=None,
        sector=None,
    )
    score, temperature, _ = calculate_lead_score(lead)
    assert score == 20
    assert temperature == "cold"
