import asyncio
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import SESSION_COOKIE, authenticate, create_session_token, require_portal_user, portal_settings
from .config import Settings, get_settings
from .database import Base, engine, ensure_lead_contact_columns, get_db
from .models import Lead, LeadStatus
from .prospecting import discover_businesses, map_complaints
from .schemas import DiscoveryRequest, GenerateRequest, LeadOut, LeadPatch, MarkContactedRequest, ProspectRequest, SuppressRequest
from .services import dispatch, enrich_with_hunter, generate_draft, is_business_email, refresh_lead_score, scan_domain

Base.metadata.create_all(bind=engine)
ensure_lead_contact_columns()
app = FastAPI(title="B2B Technographics Prospector", version="0.1.0")
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def find_lead(lead_id: int, db: Session) -> Lead:
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    return lead


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root(request: Request, settings: Settings = Depends(get_settings)):
    try:
        require_portal_user(request, settings)
        return RedirectResponse(url="/dashboard", status_code=302)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)


@app.get("/login", include_in_schema=False)
def login_page(request: Request, settings: Settings = Depends(get_settings)):
    try:
        require_portal_user(request, settings)
        return RedirectResponse(url="/dashboard", status_code=302)
    except HTTPException:
        return FileResponse(STATIC_DIR / "login.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard(request: Request, settings: Settings = Depends(get_settings)):
    try:
        require_portal_user(request, settings)
    except HTTPException:
        return RedirectResponse(url="/login?next=/dashboard", status_code=302)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/v1/auth/me")
def auth_me(request: Request, settings: Settings = Depends(get_settings)):
    username = require_portal_user(request, settings)
    return {"username": username}


@app.post("/api/v1/auth/login")
def auth_login(
    response: Response,
    payload: dict = Body(...),
    settings: Settings = Depends(get_settings),
):
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", "")).strip()
    if not authenticate(username, password, settings):
        raise HTTPException(status_code=401, detail="Credenciais invalidas")
    _, _, secret, ttl_seconds, secure_cookie = portal_settings(settings)
    token = create_session_token(username, secret, ttl_seconds)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=secure_cookie,
        max_age=ttl_seconds,
        path="/",
    )
    return {"status": "ok", "username": username}


@app.post("/api/v1/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(key=SESSION_COOKIE, path="/")
    return {"status": "ok"}


@app.post("/api/v1/leads/discover", response_model=list[LeadOut])
async def discover(payload: DiscoveryRequest, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    result = []
    for domain in payload.domains:
        lead = db.scalar(select(Lead).where(Lead.domain == domain))
        scan = await scan_domain(domain, settings)
        if lead is None:
            lead = Lead(domain=domain)
            db.add(lead)
        lead.crm, lead.confidence, lead.evidence = scan["crm"], scan["confidence"], scan["evidence"]
        if not is_business_email(lead.contact_email):
            lead.contact_email = scan["public_emails"][0] if scan["public_emails"] else None
        lead.contact_phone = scan["public_phones"][0] if scan["public_phones"] else None
        lead.contact_whatsapp = scan["public_whatsapps"][0] if scan["public_whatsapps"] else None
        refresh_lead_score(lead)
        result.append(lead)
    db.commit()
    return result


@app.post("/api/v1/prospect/run", response_model=list[LeadOut])
async def run_prospecting(
    payload: ProspectRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Descobre empresas e executa todo o enriquecimento sem receber domínios manualmente."""
    candidate_pool = min(1000, max(200, payload.limit * 8))
    try:
        prospects = await discover_businesses(payload.city, payload.state, payload.segments, candidate_pool, settings)
    except Exception as exc:
        prospects = []
    if payload.only_new:
        existing_domains = set(db.scalars(select(Lead.domain)))
        prospects = [item for item in prospects if item["domain"] not in existing_domains][:payload.limit]
    else:
        prospects = prospects[:payload.limit]
    if not prospects and not payload.only_new:
        broad_city = payload.city.strip().lower() in {"", "santa catarina", "sc", "estado de santa catarina"}
        location_pattern = f"%/{payload.state}" if broad_city else f"{payload.city}/%"
        cached = list(db.scalars(
            select(Lead)
            .where(Lead.location.ilike(location_pattern), Lead.status != LeadStatus.SUPPRESSED.value)
            .order_by(Lead.updated_at.desc())
            .limit(payload.limit)
        ))
        prospects = [{
            "company_name": lead.company_name or lead.domain,
            "domain": lead.domain,
            "location": lead.location or f"{payload.city}/{payload.state}",
            "sector": lead.sector,
            "source": lead.discovery_source or f"https://{lead.domain}",
            "segment_match": True,
        } for lead in cached]
    if not prospects:
        return []
    semaphore = asyncio.Semaphore(max(1, settings.discovery_concurrency))

    async def scan(item: dict) -> tuple[dict, dict]:
        async with semaphore:
            return item, await scan_domain(item["domain"], settings)

    scanned = await asyncio.gather(*(scan(item) for item in prospects))
    complaint_candidates = [item for item, _ in scanned][:max(payload.target_contacts, 100)]
    researched = await map_complaints(complaint_candidates, settings, payload.include_complaints)
    pain_by_domain = {item["domain"]: item for item in researched}
    result = []
    for item, scan_result in scanned:
        item = {**item, **pain_by_domain.get(item["domain"], {})}
        lead = db.scalar(select(Lead).where(Lead.domain == item["domain"]))
        if lead is None:
            lead = Lead(domain=item["domain"])
            db.add(lead)
        lead.company_name = item["company_name"] or lead.company_name
        lead.location = item["location"]
        lead.sector = item.get("sector") or lead.sector
        lead.discovery_source = item["source"]
        lead.opportunity_type = item.get("opportunity_type") or lead.opportunity_type
        lead.crm = scan_result["crm"]
        lead.confidence = scan_result["confidence"]
        lead.evidence = scan_result["evidence"]
        lead.pain_score = item.get("pain_score", 0)
        lead.pain_summary = item.get("pain_summary")
        lead.pain_source = item.get("pain_source")
        if not is_business_email(lead.contact_email):
            lead.contact_email = scan_result["public_emails"][0] if scan_result["public_emails"] else None
        lead.contact_phone = scan_result["public_phones"][0] if scan_result["public_phones"] else lead.contact_phone
        lead.contact_whatsapp = scan_result["public_whatsapps"][0] if scan_result["public_whatsapps"] else lead.contact_whatsapp
        refresh_lead_score(lead)
        if lead.lead_score >= payload.min_score and lead.status != LeadStatus.SUPPRESSED.value:
            result.append(lead)
    db.commit()
    result.sort(key=lambda lead: (
        bool(lead.contact_whatsapp or lead.contact_email or lead.contact_phone),
        lead.lead_score,
        lead.confidence,
    ), reverse=True)
    return result[:payload.limit]


@app.get("/api/v1/leads", response_model=list[LeadOut])
def list_leads(
    status: str | None = Query(default=None),
    temperature: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = select(Lead).order_by(Lead.id.desc())
    if status:
        query = query.where(Lead.status == status)
    if temperature:
        query = query.where(Lead.temperature == temperature)
    if q:
        term = f"%{q.strip()}%"
        query = query.where(or_(Lead.company_name.ilike(term), Lead.domain.ilike(term), Lead.crm.ilike(term), Lead.opportunity_type.ilike(term), Lead.location.ilike(term)))
    return list(db.scalars(query.limit(limit)))


@app.get("/api/v1/leads/hot", response_model=list[LeadOut])
def hot_leads(
    min_score: int = Query(default=70, ge=0, le=100),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = (
        select(Lead)
        .where(Lead.lead_score >= min_score, Lead.status != LeadStatus.SUPPRESSED.value)
        .order_by(Lead.lead_score.desc(), Lead.confidence.desc())
        .limit(limit)
    )
    return list(db.scalars(query))


@app.get("/api/v1/leads/{lead_id}", response_model=LeadOut)
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    return find_lead(lead_id, db)


@app.patch("/api/v1/leads/{lead_id}", response_model=LeadOut)
def patch_lead(lead_id: int, payload: LeadPatch, db: Session = Depends(get_db)):
    lead = find_lead(lead_id, db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(lead, key, str(value) if value is not None else None)
    refresh_lead_score(lead)
    db.commit()
    return lead


@app.post("/api/v1/leads/{lead_id}/mark-contacted", response_model=LeadOut)
def mark_contacted(lead_id: int, payload: MarkContactedRequest, db: Session = Depends(get_db)):
    lead = find_lead(lead_id, db)
    if lead.status == LeadStatus.SUPPRESSED.value:
        raise HTTPException(status_code=409, detail="Lead está na lista de supressão")
    lead.status = LeadStatus.SENT.value
    lead.contact_channel = payload.channel
    lead.contacted_at = datetime.now(timezone.utc)
    db.commit()
    return lead


@app.post("/api/v1/leads/{lead_id}/reopen", response_model=LeadOut)
def reopen_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = find_lead(lead_id, db)
    lead.status = LeadStatus.DISCOVERED.value
    lead.contact_channel = None
    lead.contacted_at = None
    db.commit()
    return lead


@app.post("/api/v1/leads/{lead_id}/enrich", response_model=LeadOut)
async def enrich(lead_id: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    lead = find_lead(lead_id, db)
    try:
        await enrich_with_hunter(lead, settings)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha no enriquecimento: {exc}") from exc
    lead.status = LeadStatus.ENRICHED.value
    refresh_lead_score(lead)
    db.commit()
    return lead


@app.post("/api/v1/leads/{lead_id}/generate", response_model=LeadOut)
def generate(lead_id: int, payload: GenerateRequest, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    lead = find_lead(lead_id, db)
    if lead.status == LeadStatus.SUPPRESSED.value:
        raise HTTPException(status_code=409, detail="Lead está na lista de supressão")
    draft = generate_draft(lead, payload, settings)
    lead.email_subject, lead.email_body = draft["subject"], draft["body"]
    lead.status = LeadStatus.DRAFTED.value
    db.commit()
    return lead


@app.post("/api/v1/leads/{lead_id}/approve", response_model=LeadOut)
def approve(lead_id: int, db: Session = Depends(get_db)):
    lead = find_lead(lead_id, db)
    if lead.status != LeadStatus.DRAFTED.value or not lead.contact_email:
        raise HTTPException(status_code=409, detail="É necessário ter rascunho e e-mail antes da aprovação")
    lead.status = LeadStatus.APPROVED.value
    db.commit()
    return lead


@app.post("/api/v1/leads/{lead_id}/send")
async def send(lead_id: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    lead = find_lead(lead_id, db)
    if lead.status != LeadStatus.APPROVED.value:
        raise HTTPException(status_code=409, detail="Somente leads aprovados podem ser enviados")
    try:
        result = await dispatch(lead, settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha no provedor de outreach: {exc}") from exc
    lead.status = LeadStatus.SENT.value
    lead.contact_channel = "email"
    lead.contacted_at = datetime.now(timezone.utc)
    db.commit()
    return result


@app.post("/api/v1/leads/{lead_id}/suppress", response_model=LeadOut)
def suppress(lead_id: int, payload: SuppressRequest, db: Session = Depends(get_db)):
    lead = find_lead(lead_id, db)
    lead.status = LeadStatus.SUPPRESSED.value
    lead.suppression_reason = payload.reason
    db.commit()
    return lead
