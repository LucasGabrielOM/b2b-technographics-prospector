def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_manual_lead_pipeline_requires_email_and_approval(client, monkeypatch):
    async def fake_scan(domain, settings):
        return "Bitrix24", 0.85, [{"source": f"https://{domain}", "technology": "Bitrix24"}]

    monkeypatch.setattr("app.main.scan_domain", fake_scan)
    lead = client.post("/api/v1/leads/discover", json={"domains": ["Example.com/path"]}).json()[0]
    assert lead["domain"] == "example.com"
    assert lead["crm"] == "Bitrix24"

    generated = client.post(f"/api/v1/leads/{lead['id']}/generate", json={}).json()
    assert generated["status"] == "drafted"
    assert client.post(f"/api/v1/leads/{lead['id']}/approve").status_code == 409

    client.patch(f"/api/v1/leads/{lead['id']}", json={"contact_email": "buyer@example.com"})
    approved = client.post(f"/api/v1/leads/{lead['id']}/approve").json()
    assert approved["status"] == "approved"
    assert client.post(f"/api/v1/leads/{lead['id']}/send").status_code == 409


def test_suppressed_lead_cannot_generate(client, monkeypatch):
    async def fake_scan(domain, settings):
        return None, 0, []

    monkeypatch.setattr("app.main.scan_domain", fake_scan)
    lead = client.post("/api/v1/leads/discover", json={"domains": ["example.org"]}).json()[0]
    client.post(f"/api/v1/leads/{lead['id']}/suppress", json={"reason": "Opt-out solicitado"})
    assert client.post(f"/api/v1/leads/{lead['id']}/generate", json={}).status_code == 409

