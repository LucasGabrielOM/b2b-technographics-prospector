from types import SimpleNamespace

from bs4 import BeautifulSoup

from app.services import _public_emails, _public_phones, calculate_lead_score, is_business_email


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
