from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class DiscoveryRequest(BaseModel):
    domains: list[str] = Field(min_length=1, max_length=100)

    @field_validator("domains")
    @classmethod
    def normalize_domains(cls, values: list[str]) -> list[str]:
        cleaned = []
        for value in values:
            domain = value.strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
            if domain and domain not in cleaned:
                cleaned.append(domain)
        return cleaned


class ProspectRequest(BaseModel):
    city: str = Field(default="Florianópolis", min_length=2, max_length=100)
    state: str = Field(default="Santa Catarina", min_length=2, max_length=100)
    segments: list[str] = Field(
        default_factory=lambda: ["imobiliária", "concessionária", "loja", "clínica"],
        min_length=1,
        max_length=12,
    )
    limit: int = Field(default=100, ge=1, le=150)
    target_contacts: int = Field(default=50, ge=1, le=100)
    min_score: int = Field(default=0, ge=0, le=100)
    include_complaints: bool = True
    only_new: bool = True


class LeadPatch(BaseModel):
    company_name: str | None = None
    sector: str | None = None
    company_size: str | None = None
    contact_name: str | None = None
    contact_role: str | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=40)
    contact_whatsapp: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=2000)


class MarkContactedRequest(BaseModel):
    channel: str = Field(default="manual", pattern="^(whatsapp|email|phone|manual)$")


class GenerateRequest(BaseModel):
    services: list[str] = Field(default_factory=lambda: ["automação de processos", "integração de APIs"])
    sender_name: str = "Especialista em Automação"
    sender_company: str = "Sua Empresa"


class SuppressRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=240)


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company_name: str | None
    domain: str
    sector: str | None
    company_size: str | None
    crm: str | None
    confidence: float
    evidence: list
    lead_score: int
    temperature: str
    score_reasons: list
    contact_name: str | None
    contact_role: str | None
    contact_email: str | None
    contact_phone: str | None
    contact_whatsapp: str | None
    email_subject: str | None
    email_body: str | None
    status: str
    suppression_reason: str | None
    location: str | None
    discovery_source: str | None
    pain_score: int
    pain_summary: str | None
    pain_source: str | None
    notes: str | None
    contact_channel: str | None
    contacted_at: datetime | None
