from types import SimpleNamespace

from bs4 import BeautifulSoup

from app.config import Settings
from app.prospecting import discover_from_google_places, score_google_review_signals
from app.services import _public_emails, _public_phones, calculate_lead_score, is_business_email, refresh_lead_score


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
    assert any("canal de contato" in reason for reason in reasons)


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


def test_refresh_score_requires_contact_for_hot_lead():
    lead = SimpleNamespace(
        crm="RD Station",
        confidence=0.95,
        evidence=[{"source": "https://example.com"}, {"source": "https://example.com/contato"}],
        contact_email=None,
        contact_whatsapp=None,
        contact_phone=None,
        company_name="Example",
        sector="Varejo",
        pain_score=85,
        pain_summary="Relatos publicos sobre demora no atendimento.",
        pain_source="https://www.reclameaqui.com.br/empresa/example",
        opportunity_type="recuperacao de atendimento",
    )

    refresh_lead_score(lead)

    assert lead.lead_score == 60
    assert lead.temperature == "warm"
    assert any("sem canal de contato" in reason for reason in lead.score_reasons)


def test_refresh_score_explains_hot_lead_source():
    lead = SimpleNamespace(
        crm=None,
        confidence=0,
        evidence=[],
        contact_email="vendas@example.com",
        contact_whatsapp=None,
        contact_phone=None,
        company_name="Example",
        sector="Varejo",
        pain_score=80,
        pain_summary="Relatos publicos indicam falta de retorno.",
        pain_source="https://www.reclameaqui.com.br/empresa/example",
        opportunity_type="recuperacao de atendimento",
    )

    refresh_lead_score(lead)

    assert lead.temperature == "hot"
    assert any("Motivo:" in reason for reason in lead.score_reasons)
    assert any("Fonte publica:" in reason for reason in lead.score_reasons)


def test_public_email_prefers_business_domain_and_ignores_free_mail():
    content = "marcio.fotog@gmail.com email@email.com contato@empresa.com.br b2b@empresa.com.br"

    assert _public_emails(content, "empresa.com.br") == [
        "b2b@empresa.com.br",
        "contato@empresa.com.br",
    ]
    assert not is_business_email("pessoa@gmail.com")
    assert is_business_email("vendas@empresa.com.br")


def test_public_phones_extracts_tel_and_whatsapp_links():
    soup = BeautifulSoup(
        '<a href="tel:+55 48 3333-4444">Telefone</a><a href="https://wa.me/5548999998888">WhatsApp</a>',
        "html.parser",
    )

    phones, whatsapps = _public_phones(soup)
    assert phones == ["+554833334444"]
    assert whatsapps == ["+5548999998888"]


def test_toll_free_number_is_not_treated_as_whatsapp():
    soup = BeautifulSoup('<a href="https://wa.me/08009401120">Contato</a>', "html.parser")

    phones, whatsapps = _public_phones(soup)
    assert phones == []
    assert whatsapps == []


def test_whatsapp_widget_inside_script_is_detected():
    soup = BeautifulSoup(
        '<script>window.supportLink="https:\\/\\/api.whatsapp.com\\/send?phone=5548999997777";</script>',
        "html.parser",
    )

    _, whatsapps = _public_phones(soup)

    assert whatsapps == ["+5548999997777"]


def test_google_reviews_generate_explainable_pain_signal():
    analysis = score_google_review_signals({
        "name": "Empresa Teste",
        "business_status": "OPERATIONAL",
        "rating": 3.2,
        "review_count": 84,
        "google_maps_url": "https://maps.google.com/?cid=123",
        "reviews": [
            {"rating": 1, "text": "Muita demora e ninguém atende o telefone."},
            {"rating": 2, "text": "Sem retorno no WhatsApp e suporte não resolveu."},
            {"rating": 5, "text": "Atendimento excelente e rápido."},
        ],
    })

    assert analysis["pain_score"] >= 55
    assert analysis["review_signal_count"] == 2
    assert "demora no atendimento" in analysis["review_pain_themes"]
    assert "2 de 3 avaliações" in analysis["pain_summary"]
    assert analysis["pain_source"] == "https://maps.google.com/?cid=123"
    assert any(item["type"] == "public_review_signal" for item in analysis["evidence"])


def test_google_company_discovery_requests_reviews_and_keeps_their_score(monkeypatch):
    import asyncio

    calls = []

    async def fake_google(query, settings, *, limit, include_contacts, include_reviews):
        calls.append((include_contacts, include_reviews))
        return {"places": [{
            "place_id": "company-place",
            "name": "Empresa Exemplo",
            "business_status": "OPERATIONAL",
            "primary_type": "store",
            "phone": "(48) 3333-4444",
            "website": "https://empresaexemplo.com.br",
            "google_maps_url": "https://maps.google.com/?cid=456",
            "rating": 3.1,
            "review_count": 72,
            "reviews": [
                {"rating": 1, "text": "Demora e ninguém atende."},
                {"rating": 2, "text": "Sem retorno no WhatsApp."},
            ],
        }]}

    monkeypatch.setattr("app.prospecting.search_google_places", fake_google)
    results = asyncio.run(discover_from_google_places(
        "Florianopolis",
        "Santa Catarina",
        ["loja"],
        5,
        Settings(google_maps_api_key="test-key"),
    ))

    assert calls == [(True, True)]
    assert results[0]["domain"] == "empresaexemplo.com.br"
    assert results[0]["pain_score"] >= 55
    assert results[0]["pain_source"] == "https://maps.google.com/?cid=456"
