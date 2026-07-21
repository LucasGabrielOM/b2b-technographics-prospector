def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


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
