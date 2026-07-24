import asyncio
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import SESSION_COOKIE, authenticate, create_session_token, hash_password, portal_settings, require_portal_admin, require_portal_user
from .config import Settings, get_settings
from .database import Base, engine, ensure_lead_contact_columns, get_db
from .models import Lead, LeadStatus, PortalUser
from .prospecting import discover_businesses, map_complaints
from .schemas import DiscoveryRequest, GenerateRequest, LeadOut, LeadPatch, MarkContactedRequest, PortalPasswordReset, PortalUserCreate, PortalUserOut, PortalUserPatch, ProspectRequest, SchoolProspectRequest, SuppressRequest
from .school_prospecting import INEP_SOURCE_URL, enrich_school_batch, school_evidence, select_schools
from .services import dispatch, enrich_with_hunter, generate_draft, is_business_email, refresh_lead_score, scan_domain

Base.metadata.create_all(bind=engine)
ensure_lead_contact_columns()
app = FastAPI(
    title="B2B Technographics Prospector",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
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


@app.get("/openapi.json", include_in_schema=False)
def protected_openapi(request: Request, settings: Settings = Depends(get_settings)):
    require_portal_admin(request, settings)
    return JSONResponse(app.openapi())


@app.get("/docs", include_in_schema=False)
def protected_docs(request: Request, settings: Settings = Depends(get_settings)):
    require_portal_admin(request, settings)
    return get_swagger_ui_html(openapi_url="/openapi.json", title="LeadPilot API")


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


@app.get("/leads", include_in_schema=False)
def leads_page(request: Request, settings: Settings = Depends(get_settings)):
    try:
        require_portal_user(request, settings)
    except HTTPException:
        return RedirectResponse(url="/login?next=/leads", status_code=302)
    return FileResponse(STATIC_DIR / "leads.html")


@app.get("/api/v1/auth/me")
def auth_me(request: Request, settings: Settings = Depends(get_settings)):
    return require_portal_user(request, settings).as_dict()


@app.post("/api/v1/auth/login")
def auth_login(
    response: Response,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", "")).strip()
    identity = authenticate(username, password, settings, db)
    if not identity:
        raise HTTPException(status_code=401, detail="Credenciais invalidas")
    _, _, secret, ttl_seconds, secure_cookie = portal_settings(settings)
    token = create_session_token(identity, secret, ttl_seconds)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=secure_cookie,
        max_age=ttl_seconds,
        path="/",
    )
    return {"status": "ok", **identity.as_dict()}


@app.post("/api/v1/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(key=SESSION_COOKIE, path="/")
    return {"status": "ok"}


@app.get("/api/v1/admin/users", response_model=list[PortalUserOut])
def list_portal_users(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    require_portal_admin(request, settings)
    return list(db.scalars(select(PortalUser).order_by(PortalUser.created_at.desc())))


@app.post("/api/v1/admin/users", response_model=PortalUserOut, status_code=201)
def create_portal_user(
    request: Request,
    payload: PortalUserCreate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    require_portal_admin(request, settings)
    admin_username, _, _, _, _ = portal_settings(settings)
    if payload.username == admin_username.strip().lower():
        raise HTTPException(status_code=409, detail="Este nome de usuário pertence ao administrador principal")
    if db.scalar(select(PortalUser).where(PortalUser.username == payload.username)):
        raise HTTPException(status_code=409, detail="Nome de usuário já cadastrado")
    user = PortalUser(
        username=payload.username,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        active=True,
    )
    db.add(user)
    db.commit()
    return user


@app.patch("/api/v1/admin/users/{user_id}", response_model=PortalUserOut)
def patch_portal_user(
    user_id: int,
    request: Request,
    payload: PortalUserPatch,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    require_portal_admin(request, settings)
    user = db.get(PortalUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, key, value.strip() if isinstance(value, str) else value)
    db.commit()
    return user


@app.post("/api/v1/admin/users/{user_id}/reset-password")
def reset_portal_user_password(
    user_id: int,
    request: Request,
    payload: PortalPasswordReset,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    require_portal_admin(request, settings)
    user = db.get(PortalUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    user.password_hash = hash_password(payload.password)
    db.commit()
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
    quick_mode = not payload.include_complaints
    discovery_timeout = 18 if quick_mode else 45
    scan_timeout = 8 if quick_mode else max(15, int(settings.request_timeout_seconds * 2))

    candidate_pool = min(80, max(30, payload.limit * 4, payload.target_contacts * 4)) if quick_mode else min(120, max(20, payload.limit * 5, payload.target_contacts * 5))
    try:
        prospects = await asyncio.wait_for(
            discover_businesses(payload.city, payload.state, payload.segments, candidate_pool, settings),
            timeout=discovery_timeout,
        )
    except Exception:
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
            max_pages = 1 if quick_mode else 5
            try:
                scan_result = await asyncio.wait_for(
                    scan_domain(item["domain"], settings, max_pages=max_pages),
                    timeout=scan_timeout,
                )
            except Exception:
                scan_result = {"crm": None, "confidence": 0.0, "evidence": [], "public_emails": [], "public_phones": [], "public_whatsapps": [], "pages_scanned": 0}
            return item, scan_result

    tasks = [asyncio.create_task(scan(item)) for item in prospects]
    done, pending = await asyncio.wait(tasks, timeout=30 if quick_mode else 75)
    for task in pending:
        task.cancel()
    scanned = []
    for task in done:
        if task.cancelled():
            continue
        try:
            scanned.append(task.result())
        except Exception:
            continue
    if not scanned:
        return []
    complaint_candidates = [item for item, _ in scanned][:payload.target_contacts]
    researched = await map_complaints(complaint_candidates, settings, True) if payload.include_complaints else []
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


@app.post("/api/v1/schools/run", response_model=list[LeadOut])
async def run_school_prospecting(
    payload: SchoolProspectRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Return a fast, deduplicated batch of active private schools from INEP."""
    existing_external_ids: set[str] = set()
    if payload.only_new:
        existing_external_ids = {
            value for value in db.scalars(
                select(Lead.external_id).where(Lead.external_id.is_not(None))
            ) if value
        }
    candidates = select_schools(
        existing_external_ids=existing_external_ids,
        states=payload.states,
        cities=payload.cities,
        private_category=payload.private_category,
        require_phone=payload.require_phone,
        limit=min(180, payload.limit + payload.enrich_cnpj_limit),
    )
    if not candidates:
        return []
    candidates = await enrich_school_batch(candidates, settings, payload.enrich_cnpj_limit)
    result: list[Lead] = []
    for school in candidates:
        if school.get("registry_checked") and not school.get("registry_active"):
            continue
        external_id = f"inep:{school['school_code']}"
        lead = db.scalar(select(Lead).where(Lead.external_id == external_id))
        if lead is None:
            lead = db.scalar(select(Lead).where(Lead.domain == f"inep-{school['school_code']}.school"))
        if lead is None:
            lead = Lead(domain=f"inep-{school['school_code']}.school", external_id=external_id)
            db.add(lead)
        lead.lead_type = "school"
        lead.external_id = external_id
        lead.registration_number = school.get("cnpj")
        lead.company_name = school["school_name"]
        lead.location = f"{school['city']}/{school['state']}"
        lead.sector = "educacao privada"
        lead.company_size = school.get("company_size") or lead.company_size
        lead.opportunity_type = "licenca SaaS e automacao para escola"
        lead.discovery_source = INEP_SOURCE_URL
        lead.crm = None
        lead.confidence = 0.0
        lead.evidence = school_evidence(school)
        lead.pain_score = 0
        lead.pain_summary = None
        lead.pain_source = None
        lead.contact_name = school.get("contact_name") or lead.contact_name
        lead.contact_role = school.get("contact_role") or lead.contact_role
        lead.contact_email = school.get("contact_email") or lead.contact_email
        lead.contact_phone = school.get("contact_phone") or school.get("phone") or lead.contact_phone
        lead.contact_whatsapp = school.get("contact_whatsapp") or lead.contact_whatsapp
        lead.website_url = school.get("website_url") or lead.website_url
        stages = ", ".join(school.get("stages") or []) or "não informadas"
        contact_origin = "CNPJ/BrasilAPI" if school.get("registry_checked") else "Censo Escolar INEP 2025"
        lead.notes = (
            f"Endereço: {school.get('address') or 'não informado'}. "
            f"Etapas: {stages}. Código INEP: {school['school_code']}. "
            f"Origem do contato: {contact_origin}."
        )
        refresh_lead_score(lead)
        result.append(lead)
        if len(result) >= payload.limit:
            break
    db.commit()
    result.sort(
        key=lambda lead: (
            bool(lead.contact_whatsapp),
            bool(lead.contact_email),
            bool(lead.contact_name),
            lead.lead_score,
        ),
        reverse=True,
    )
    return result


@app.get("/api/v1/leads", response_model=list[LeadOut])
def list_leads(
    status: str | None = Query(default=None),
    temperature: str | None = Query(default=None),
    lead_type: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = select(Lead).order_by(Lead.id.desc())
    if status:
        query = query.where(Lead.status == status)
    if temperature:
        query = query.where(Lead.temperature == temperature)
    if lead_type:
        query = query.where(Lead.lead_type == lead_type)
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
