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


class LeadPatch(BaseModel):
    company_name: str | None = None
    sector: str | None = None
    company_size: str | None = None
    contact_name: str | None = None
    contact_role: str | None = None
    contact_email: EmailStr | None = None


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
    contact_name: str | None
    contact_role: str | None
    contact_email: str | None
    email_subject: str | None
    email_body: str | None
    status: str
    suppression_reason: str | None

