def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert "Central de oportunidades" in dashboard.text


def test_manual_lead_pipeline_requires_email_and_approval(client, monkeypatch):
    async def fake_scan(domain, settings):
        return {"crm": "Bitrix24", "confidence": 0.85, "evidence": [{"source": f"https://{domain}", "technology": "Bitrix24"}], "public_emails": [], "public_phones": ["+5548999999999"], "public_whatsapps": ["+5548999999999"], "pages_scanned": 1}

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

    client.patch(f"/api/v1/leads/{lead['id']}", json={"contact_email": "buyer@example.com"})
    hot = client.get("/api/v1/leads/hot", params={"min_score": 70}).json()
    assert hot[0]["id"] == lead["id"]
    assert hot[0]["temperature"] == "hot"
    approved = client.post(f"/api/v1/leads/{lead['id']}/approve").json()
    assert approved["status"] == "approved"
    assert client.post(f"/api/v1/leads/{lead['id']}/send").status_code == 409


def test_suppressed_lead_cannot_generate(client, monkeypatch):
    async def fake_scan(domain, settings):
        return {"crm": None, "confidence": 0, "evidence": [], "public_emails": [], "public_phones": [], "public_whatsapps": [], "pages_scanned": 1}

    monkeypatch.setattr("app.main.scan_domain", fake_scan)
    lead = client.post("/api/v1/leads/discover", json={"domains": ["example.org"]}).json()[0]
    client.post(f"/api/v1/leads/{lead['id']}/suppress", json={"reason": "Opt-out solicitado"})
    assert client.post(f"/api/v1/leads/{lead['id']}/generate", json={}).status_code == 409


def test_autonomous_prospecting_discovers_domain_contact_and_pain(client, monkeypatch):
    async def fake_discover(city, state, segments, limit, settings):
        return [{
            "company_name": "Empresa Automática",
            "domain": "empresa.com.br",
            "location": "Florianópolis/Santa Catarina",
            "sector": "loja",
            "source": "https://www.openstreetmap.org/node/1",
            "segment_match": True,
        }]

    async def fake_complaints(prospects, settings, enabled):
        return [{**prospects[0], "pain_score": 75, "pain_summary": "Demora e falta de retorno.", "pain_source": "https://www.reclameaqui.com.br/empresa/teste"}]

    async def fake_scan(domain, settings):
        return {"crm": None, "confidence": 0, "evidence": [], "public_emails": ["contato@empresa.com.br"], "public_phones": [], "public_whatsapps": ["+5548999999999"], "pages_scanned": 2}

    monkeypatch.setattr("app.main.discover_businesses", fake_discover)
    monkeypatch.setattr("app.main.map_complaints", fake_complaints)
    monkeypatch.setattr("app.main.scan_domain", fake_scan)
    response = client.post("/api/v1/prospect/run", json={"limit": 10, "min_score": 45})
    assert response.status_code == 200
    lead = response.json()[0]
    assert lead["domain"] == "empresa.com.br"
    assert lead["company_name"] == "Empresa Automática"
    assert lead["pain_score"] == 75
    assert lead["lead_score"] == 75
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
