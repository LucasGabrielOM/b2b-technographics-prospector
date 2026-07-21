from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import Base, engine, get_db
from .models import Lead, LeadStatus
from .schemas import DiscoveryRequest, GenerateRequest, LeadOut, LeadPatch, SuppressRequest
from .services import dispatch, enrich_with_hunter, generate_draft, is_business_email, refresh_lead_score, scan_domain

Base.metadata.create_all(bind=engine)
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
        refresh_lead_score(lead)
        result.append(lead)
    db.commit()
    return result


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
