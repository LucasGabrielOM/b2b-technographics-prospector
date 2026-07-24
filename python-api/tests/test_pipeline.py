def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/login").status_code == 200
    assert client.get("/dashboard", follow_redirects=False).status_code == 302
    assert client.get("/leads", follow_redirects=False).status_code == 302
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "demo1234"})
    assert login.status_code == 200
    assert login.json()["role"] == "admin"
    assert login.json()["is_admin"] is True
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert "LeadPilot" in dashboard.text
    leads_page = client.get("/leads")
    assert leads_page.status_code == 200
    assert "Central de leads" in leads_page.text
    assert client.get("/docs").status_code == 200


def test_admin_creates_user_with_restricted_session(client):
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "demo1234"}).status_code == 200
    created = client.post("/api/v1/admin/users", json={
        "username": "comercial.teste",
        "display_name": "Comercial Teste",
        "password": "SenhaForte#2026",
        "role": "user",
    })
    assert created.status_code == 201
    assert created.json()["role"] == "user"
    assert "password" not in created.json()
    assert client.get("/api/v1/admin/users").status_code == 200

    client.post("/api/v1/auth/logout")
    login = client.post("/api/v1/auth/login", json={
        "username": "comercial.teste",
        "password": "SenhaForte#2026",
    })
    assert login.status_code == 200
    assert login.json()["role"] == "user"
    assert login.json()["is_admin"] is False
    assert client.get("/dashboard").status_code == 200
    assert client.get("/leads").status_code == 200
    assert client.get("/api/v1/admin/users").status_code == 403
    assert client.get("/docs").status_code == 403


def test_manual_lead_pipeline_requires_email_and_approval(client, monkeypatch):
    async def fake_scan(domain, settings, max_pages=5):
        return {
            "crm": "Bitrix24",
            "confidence": 0.85,
            "evidence": [{"source": f"https://{domain}", "technology": "Bitrix24"}],
            "public_emails": [],
            "public_phones": ["+5548999999999"],
            "public_whatsapps": ["+5548999999999"],
            "pages_scanned": 1,
        }

    monkeypatch.setattr("app.main.scan_domain", fake_scan)
    lead = client.post("/api/v1/leads/discover", json={"domains": ["Example.com/path"]}).json()[0]
    assert lead["domain"] == "example.com"
    assert lead["crm"] == "Bitrix24"
    assert lead["lead_score"] == 70
    assert lead["temperature"] == "hot"
    assert lead["contact_phone"] == "+5548999999999"
    assert lead["contact_whatsapp"] == "+5548999999999"

    generated = client.post(f"/api/v1/leads/{lead['id']}/generate", json={}).json()
    assert generated["status"] == "drafted"
    assert client.post(f"/api/v1/leads/{lead['id']}/approve").status_code == 409

    patched = client.patch(f"/api/v1/leads/{lead['id']}", json={
        "contact_email": "buyer@example.com",
        "email_subject": "Assunto comercial revisado",
        "email_body": "Mensagem revisada antes do envio.",
    }).json()
    assert patched["email_subject"] == "Assunto comercial revisado"
    assert patched["email_body"] == "Mensagem revisada antes do envio."
    hot = client.get("/api/v1/leads/hot", params={"min_score": 70}).json()
    assert hot[0]["id"] == lead["id"]
    assert hot[0]["temperature"] == "hot"
    approved = client.post(f"/api/v1/leads/{lead['id']}/approve").json()
    assert approved["status"] == "approved"
    assert client.post(f"/api/v1/leads/{lead['id']}/send").status_code == 409


def test_suppressed_lead_cannot_generate(client, monkeypatch):
    async def fake_scan(domain, settings, max_pages=5):
        return {
            "crm": None,
            "confidence": 0,
            "evidence": [],
            "public_emails": [],
            "public_phones": [],
            "public_whatsapps": [],
            "pages_scanned": 1,
        }

    monkeypatch.setattr("app.main.scan_domain", fake_scan)
    lead = client.post("/api/v1/leads/discover", json={"domains": ["example.org"]}).json()[0]
    client.post(f"/api/v1/leads/{lead['id']}/suppress", json={"reason": "Opt-out solicitado"})
    assert client.post(f"/api/v1/leads/{lead['id']}/generate", json={}).status_code == 409


def test_autonomous_prospecting_discovers_domain_contact_and_pain(client, monkeypatch):
    async def fake_discover(city, state, segments, limit, settings):
        return [{
            "company_name": "Empresa Automatica",
            "domain": "empresa.com.br",
            "location": "Florianopolis/Santa Catarina",
            "sector": "loja",
            "source": "https://www.openstreetmap.org/node/1",
            "segment_match": True,
        }]

    async def fake_complaints(prospects, settings, enabled):
        return [{
            **prospects[0],
            "pain_score": 75,
            "pain_summary": "Demora e falta de retorno.",
            "pain_source": "https://www.reclameaqui.com.br/empresa/teste",
            "opportunity_type": "recuperacao de atendimento",
        }]

    async def fake_scan(domain, settings, max_pages=5):
        return {
            "crm": None,
            "confidence": 0,
            "evidence": [],
            "public_emails": ["contato@empresa.com.br"],
            "public_phones": [],
            "public_whatsapps": ["+5548999999999"],
            "pages_scanned": max_pages,
        }

    monkeypatch.setattr("app.main.discover_businesses", fake_discover)
    monkeypatch.setattr("app.main.map_complaints", fake_complaints)
    monkeypatch.setattr("app.main.scan_domain", fake_scan)
    response = client.post("/api/v1/prospect/run", json={"limit": 10, "min_score": 45})
    assert response.status_code == 200
    lead = response.json()[0]
    assert lead["domain"] == "empresa.com.br"
    assert lead["company_name"] == "Empresa Automatica"
    assert lead["opportunity_type"] == "recuperacao de atendimento"
    assert lead["pain_score"] == 75
    assert lead["lead_score"] == 91
    assert lead["contact_email"] == "contato@empresa.com.br"
    assert lead["contact_whatsapp"] == "+5548999999999"

    repeated = client.post("/api/v1/prospect/run", json={"limit": 10, "min_score": 0}).json()
    assert repeated == []

    async def unavailable_discovery(city, state, segments, limit, settings):
        return []

    monkeypatch.setattr("app.main.discover_businesses", unavailable_discovery)
    cached = client.post("/api/v1/prospect/run", json={"limit": 10, "min_score": 45, "only_new": False}).json()
    assert cached[0]["domain"] == "empresa.com.br"
    assert cached[0]["pain_score"] == 75

    marked = client.post(f"/api/v1/leads/{lead['id']}/mark-contacted", json={"channel": "whatsapp"})
    assert marked.status_code == 200
    assert marked.json()["status"] == "sent"
    assert marked.json()["contact_channel"] == "whatsapp"
    assert marked.json()["contacted_at"] is not None
    reopened = client.post(f"/api/v1/leads/{lead['id']}/reopen").json()
    assert reopened["status"] == "discovered"
    assert reopened["contacted_at"] is None


def test_autonomous_prospecting_can_skip_slow_public_complaint_search(client, monkeypatch):
    async def fake_discover(city, state, segments, limit, settings):
        return [{
            "company_name": "Empresa Rapida",
            "domain": "rapida.com.br",
            "location": "Joinville/Santa Catarina",
            "sector": "loja",
            "source": "https://www.openstreetmap.org/node/2",
            "segment_match": True,
        }]

    async def fail_if_called(prospects, settings, enabled):
        raise AssertionError("complaint search should be skipped in quick workflow mode")

    async def fake_scan(domain, settings, max_pages=5):
        assert max_pages == 1
        return {
            "crm": "HubSpot",
            "confidence": 0.9,
            "evidence": [{"source": "https://rapida.com.br", "technology": "HubSpot"}],
            "public_emails": ["vendas@rapida.com.br"],
            "public_phones": [],
            "public_whatsapps": ["+5547999999999"],
            "pages_scanned": 1,
        }

    monkeypatch.setattr("app.main.discover_businesses", fake_discover)
    monkeypatch.setattr("app.main.map_complaints", fail_if_called)
    monkeypatch.setattr("app.main.scan_domain", fake_scan)

    response = client.post("/api/v1/prospect/run", json={"limit": 4, "target_contacts": 4, "min_score": 70, "include_complaints": False})

    assert response.status_code == 200
    lead = response.json()[0]
    assert lead["temperature"] == "hot"
    assert any("Fonte tecnica:" in reason for reason in lead["score_reasons"])


def test_autonomous_prospecting_returns_warm_qualified_crm_leads(client, monkeypatch):
    async def fake_discover(city, state, segments, limit, settings):
        return [{
            "company_name": "Empresa Morna",
            "domain": "morna.com.br",
            "location": "Blumenau/Santa Catarina",
            "sector": "varejo",
            "source": "https://www.openstreetmap.org/node/3",
            "segment_match": True,
        }]

    async def fake_scan(domain, settings, max_pages=5):
        assert max_pages == 1
        return {
            "crm": "Pipedrive",
            "confidence": 0.55,
            "evidence": [{"source": "https://morna.com.br", "technology": "Pipedrive"}],
            "public_emails": ["comercial@morna.com.br"],
            "public_phones": [],
            "public_whatsapps": [],
            "pages_scanned": 1,
        }

    monkeypatch.setattr("app.main.discover_businesses", fake_discover)
    monkeypatch.setattr("app.main.scan_domain", fake_scan)

    response = client.post("/api/v1/prospect/run", json={"limit": 8, "target_contacts": 8, "min_score": 45, "include_complaints": False})

    assert response.status_code == 200
    lead = response.json()[0]
    assert lead["domain"] == "morna.com.br"
    assert lead["lead_score"] >= 45
    assert lead["temperature"] == "warm"
    assert lead["contact_email"] == "comercial@morna.com.br"


def test_autonomous_prospecting_does_not_return_existing_leads_as_new(client, monkeypatch):
    async def first_discover(city, state, segments, limit, settings):
        return [{
            "company_name": "Empresa Cache",
            "domain": "cache.com.br",
            "location": "Itajai/Santa Catarina",
            "sector": "varejo",
            "source": "https://www.openstreetmap.org/node/4",
            "segment_match": True,
        }]

    async def fake_scan(domain, settings, max_pages=5):
        return {
            "crm": "HubSpot",
            "confidence": 0.9,
            "evidence": [{"source": "https://cache.com.br", "technology": "HubSpot"}],
            "public_emails": ["vendas@cache.com.br"],
            "public_phones": [],
            "public_whatsapps": [],
            "pages_scanned": 1,
        }

    monkeypatch.setattr("app.main.discover_businesses", first_discover)
    monkeypatch.setattr("app.main.scan_domain", fake_scan)
    created = client.post("/api/v1/prospect/run", json={"limit": 4, "min_score": 45, "include_complaints": False}).json()
    assert created[0]["domain"] == "cache.com.br"

    async def no_new_discovery(city, state, segments, limit, settings):
        return []

    monkeypatch.setattr("app.main.discover_businesses", no_new_discovery)
    fallback = client.post("/api/v1/prospect/run", json={"limit": 4, "min_score": 45, "include_complaints": False, "only_new": True}).json()
    assert fallback == []


def test_school_prospecting_returns_active_private_contacts_without_duplicates(client, monkeypatch):
    async def fake_enrich(schools, settings, limit):
        enriched = []
        for index, school in enumerate(schools):
            if index < limit:
                enriched.append({
                    **school,
                    "registry_checked": True,
                    "registry_active": True,
                    "registry_status": "ATIVA",
                    "contact_name": "Responsavel Escolar",
                    "contact_role": "Socio-Administrador",
                    "contact_email": "contato@escola.com.br",
                })
            else:
                enriched.append({**school, "registry_checked": False})
        return enriched

    monkeypatch.setattr("app.main.enrich_school_batch", fake_enrich)
    payload = {
        "limit": 100,
        "require_phone": True,
        "private_category": "1",
        "only_new": True,
        "enrich_cnpj_limit": 12,
    }
    first = client.post("/api/v1/schools/run", json=payload)
    assert first.status_code == 200
    first_leads = first.json()
    assert len(first_leads) == 100
    assert len({lead["external_id"] for lead in first_leads}) == 100
    assert all(lead["lead_type"] == "school" for lead in first_leads)
    assert all(lead["contact_phone"] for lead in first_leads)
    assert all(lead["sector"] == "educacao privada" for lead in first_leads)
    assert all(any("INEP 2025" in reason for reason in lead["score_reasons"]) for lead in first_leads)
    assert any(lead["temperature"] == "hot" for lead in first_leads)

    second_leads = client.post("/api/v1/schools/run", json=payload).json()
    assert len(second_leads) == 100
    assert {lead["external_id"] for lead in first_leads}.isdisjoint(
        {lead["external_id"] for lead in second_leads}
    )


def test_school_prospecting_filters_state_and_skips_inactive_cnpj(client, monkeypatch):
    async def fake_enrich(schools, settings, limit):
        return [
            {
                **school,
                "registry_checked": index == 0,
                "registry_active": index != 0,
                "registry_status": "BAIXADA" if index == 0 else None,
            }
            for index, school in enumerate(schools)
        ]

    monkeypatch.setattr("app.main.enrich_school_batch", fake_enrich)
    response = client.post("/api/v1/schools/run", json={
        "states": ["SC"],
        "limit": 20,
        "require_phone": True,
        "private_category": "1",
        "enrich_cnpj_limit": 1,
    })
    assert response.status_code == 200
    leads = response.json()
    assert len(leads) == 20
    assert all(lead["location"].endswith("/SC") for lead in leads)
    assert all(
        not any(item.get("status") == "BAIXADA" for item in lead["evidence"])
        for lead in leads
    )
