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
    city: str = Field(default="Santa Catarina", min_length=2, max_length=100)
    state: str = Field(default="Santa Catarina", min_length=2, max_length=100)
    segments: list[str] = Field(
        default_factory=lambda: ["imobiliaria", "concessionaria", "loja", "clinica"],
        min_length=1,
        max_length=12,
    )
    limit: int = Field(default=100, ge=1, le=150)
    target_contacts: int = Field(default=100, ge=1, le=150)
    min_score: int = Field(default=0, ge=0, le=100)
    include_complaints: bool = True
    only_new: bool = True


class SchoolProspectRequest(BaseModel):
    states: list[str] = Field(default_factory=list, max_length=27)
    cities: list[str] = Field(default_factory=list, max_length=100)
    limit: int = Field(default=100, ge=1, le=150)
    require_phone: bool = True
    private_category: str = Field(default="1", pattern="^(1|2|3|4|all)$")
    only_new: bool = True
    enrich_cnpj_limit: int = Field(default=12, ge=0, le=30)

    @field_validator("states")
    @classmethod
    def normalize_states(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().upper() for value in values if value.strip()))

    @field_validator("cities")
    @classmethod
    def normalize_cities(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class PortalUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    display_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="user", pattern="^(admin|user)$")

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lower()


class PortalUserPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=160)
    role: str | None = Field(default=None, pattern="^(admin|user)$")
    active: bool | None = None


class PortalPasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class PortalUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    role: str
    active: bool
    created_at: datetime


class LeadPatch(BaseModel):
    company_name: str | None = None
    sector: str | None = None
    company_size: str | None = None
    opportunity_type: str | None = None
    contact_name: str | None = None
    contact_role: str | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=40)
    contact_whatsapp: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=2000)


class MarkContactedRequest(BaseModel):
    channel: str = Field(default="manual", pattern="^(whatsapp|email|phone|manual)$")


class GenerateRequest(BaseModel):
    services: list[str] = Field(default_factory=lambda: ["automacao de processos", "integracao de APIs"])
    sender_name: str = "Especialista em Automacao"
    sender_company: str = "Sua Empresa"


class SuppressRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=240)


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company_name: str | None
    domain: str
    lead_type: str
    external_id: str | None
    registration_number: str | None
    website_url: str | None
    sector: str | None
    company_size: str | None
    opportunity_type: str | None
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
