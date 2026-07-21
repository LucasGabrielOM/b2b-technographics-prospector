import json
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from openai import OpenAI

from .config import Settings
from .models import Lead
from .schemas import GenerateRequest


TECH_SIGNATURES = {
    "Bitrix24": [r"bitrix24", r"bx24", r"bitrix\.info"],
    "HubSpot": [r"js\.hs-scripts\.com", r"hubspot", r"hsforms\.net"],
    "Salesforce": [r"salesforce", r"force\.com", r"pardot", r"salesforceliveagent"],
    "RD Station": [r"rdstation", r"rd\.services", r"resultadosdigitais"],
    "Pipedrive": [r"pipedrive", r"leadbooster-chat"],
}


async def scan_domain(domain: str, settings: Settings) -> tuple[str | None, float, list[dict]]:
    headers = {"User-Agent": settings.crawler_user_agent}
    evidence: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, follow_redirects=True, headers=headers) as client:
            response = await client.get(f"https://{domain}")
            response.raise_for_status()
        html = response.text[:2_000_000]
        soup = BeautifulSoup(html, "html.parser")
        searchable = " ".join(
            [html, soup.get_text(" ", strip=True)]
            + [tag.get("src", "") for tag in soup.find_all(src=True)]
            + [tag.get("href", "") for tag in soup.find_all(href=True)]
        ).lower()
        scores: dict[str, int] = {}
        for technology, patterns in TECH_SIGNATURES.items():
            matches = sorted({pattern for pattern in patterns if re.search(pattern, searchable, re.I)})
            if matches:
                scores[technology] = len(matches)
                evidence.append({"source": str(response.url), "technology": technology, "signatures": matches})
        if not scores:
            return None, 0.0, []
        crm = max(scores, key=scores.get)
        confidence = min(0.95, 0.55 + 0.15 * (scores[crm] - 1))
        return crm, confidence, [item for item in evidence if item["technology"] == crm]
    except (httpx.HTTPError, ValueError):
        return None, 0.0, []


async def enrich_with_hunter(lead: Lead, settings: Settings) -> dict:
    if not settings.hunter_api_key:
        return {"provider": "hunter", "status": "skipped", "reason": "missing_api_key"}
    params = {"domain": lead.domain, "api_key": settings.hunter_api_key, "limit": 10}
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.get("https://api.hunter.io/v2/domain-search", params=params)
        response.raise_for_status()
    emails = response.json().get("data", {}).get("emails", [])
    preferred = sorted(
        emails,
        key=lambda item: (item.get("type") != "personal", -(item.get("confidence") or 0)),
    )
    if not preferred:
        return {"provider": "hunter", "status": "not_found"}
    contact = preferred[0]
    lead.contact_email = contact.get("value")
    lead.contact_name = " ".join(filter(None, [contact.get("first_name"), contact.get("last_name")])) or None
    lead.contact_role = contact.get("position")
    return {"provider": "hunter", "status": "found", "confidence": contact.get("confidence")}


def _demo_draft(lead: Lead, request: GenerateRequest) -> dict[str, str]:
    company = lead.company_name or lead.domain
    crm = lead.crm or "seu CRM"
    services = ", ".join(request.services[:3])
    return {
        "subject": f"Uma ideia para evoluir o {crm} na {company}",
        "body": (
            f"Olá{(' ' + lead.contact_name) if lead.contact_name else ''},\n\n"
            f"Ao pesquisar a operação da {company}, encontrei sinais públicos de uso do {crm}. "
            f"Trabalhamos com {services} para reduzir tarefas manuais e melhorar a visibilidade do funil.\n\n"
            "Faria sentido uma conversa de 15 minutos para avaliarmos se há algum gargalo que valha automatizar?\n\n"
            f"Abraço,\n{request.sender_name}\n{request.sender_company}"
        ),
    }


def generate_draft(lead: Lead, request: GenerateRequest, settings: Settings) -> dict[str, str]:
    if not settings.openai_api_key:
        return _demo_draft(lead, request)
    evidence = json.dumps(lead.evidence, ensure_ascii=False)
    prompt = f"""Crie um cold email B2B em português do Brasil.

Empresa: {lead.company_name or lead.domain}
Domínio: {lead.domain}
Setor: {lead.sector or 'não informado'}
Porte: {lead.company_size or 'não informado'}
Contato/cargo: {lead.contact_name or 'não informado'} / {lead.contact_role or 'não informado'}
CRM detectado: {lead.crm or 'não confirmado'}
Evidências públicas: {evidence}
Serviços: {', '.join(request.services)}
Remetente: {request.sender_name}, {request.sender_company}

Use apenas os fatos fornecidos. Não afirme que a empresa é cliente do CRM; diga que há sinais públicos. Seja humano,
específico e direto, com no máximo 120 palavras. Inclua uma pergunta de baixa fricção. Retorne JSON válido com
exatamente as chaves subject e body. Não use Markdown.
"""
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(
        model=settings.openai_model,
        instructions="Você redige prospecção B2B factual, respeitosa e sem alegações não comprovadas.",
        input=prompt,
        text={"verbosity": "low"},
    )
    try:
        data = json.loads(response.output_text)
        return {"subject": str(data["subject"]), "body": str(data["body"])}
    except (json.JSONDecodeError, KeyError, TypeError):
        return _demo_draft(lead, request)


async def dispatch(lead: Lead, settings: Settings) -> dict:
    if not settings.outreach_enabled:
        raise RuntimeError("Envio desabilitado por OUTREACH_ENABLED=false")
    if not settings.outreach_webhook_url:
        raise RuntimeError("OUTREACH_WEBHOOK_URL não configurado")
    payload = {
        "lead_id": lead.id,
        "to": lead.contact_email,
        "subject": lead.email_subject,
        "body": lead.email_body,
        "domain": lead.domain,
    }
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.post(settings.outreach_webhook_url, json=payload)
        response.raise_for_status()
    return {"status": "sent", "provider_status": response.status_code}

