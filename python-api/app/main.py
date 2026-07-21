import asyncio

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import Base, engine, ensure_lead_contact_columns, get_db
from .models import Lead, LeadStatus
from .prospecting import discover_businesses, map_complaints
from .schemas import DiscoveryRequest, GenerateRequest, LeadOut, LeadPatch, ProspectRequest, SuppressRequest
from .services import dispatch, enrich_with_hunter, generate_draft, is_business_email, refresh_lead_score, scan_domain

Base.metadata.create_all(bind=engine)
ensure_lead_contact_columns()
app = FastAPI(title="B2B Technographics Prospector", version="0.1.0")


def find_lead(lead_id: int, db: Session) -> Lead:
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    return lead


@app.get("/health")
def health():
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
    try:
        prospects = await discover_businesses(payload.city, payload.state, payload.segments, payload.limit, settings)
    except Exception as exc:
        prospects = []
    if not prospects:
        cached = list(db.scalars(
            select(Lead)
            .where(Lead.location.ilike(f"{payload.city}/%"), Lead.status != LeadStatus.SUPPRESSED.value)
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
    contact_candidates = [
        item for item, scan_result in scanned
        if scan_result["public_emails"] or scan_result["public_phones"] or scan_result["public_whatsapps"]
    ]
    complaint_candidates = contact_candidates[:max(payload.target_contacts, 60)]
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
def list_leads(status: str | None = Query(default=None), db: Session = Depends(get_db)):
    query = select(Lead).order_by(Lead.id.desc())
    if status:
        query = query.where(Lead.status == status)
    return list(db.scalars(query))


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
    db.commit()
    return result


@app.post("/api/v1/leads/{lead_id}/suppress", response_model=LeadOut)
def suppress(lead_id: int, payload: SuppressRequest, db: Session = Depends(get_db)):
    lead = find_lead(lead_id, db)
    lead.status = LeadStatus.SUPPRESSED.value
    lead.suppression_reason = payload.reason
    db.commit()
    return lead
