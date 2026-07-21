import json
import re
from urllib.parse import parse_qs, urljoin, urlparse

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
    "RD Station": [r"rdstation", r"rd\.services", r"resultadosdigitais", r"d335luupugsy2\.cloudfront\.net"],
    "Pipedrive": [r"pipedrive", r"leadbooster-chat"],
}

CONTACT_TERMS = ("contato", "contact", "orcamento", "orçamento", "fale", "sobre", "about", "atendimento")
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?55\s*)?(?:\(?\d{2}\)?[\s.-]*)?(?:9\s*)?\d{4}[\s.-]*\d{4}")
IGNORED_EMAIL_PARTS = ("example.", "email@email", "teste@teste", "sentry", "wixpress", "cloudflare", "noreply", "no-reply")
FREE_EMAIL_DOMAINS = {
    "gmail.com", "hotmail.com", "hotmail.com.br", "outlook.com", "live.com",
    "yahoo.com", "yahoo.com.br", "icloud.com", "bol.com.br", "uol.com.br",
}
BUSINESS_EMAIL_PREFIXES = ("b2b", "comercial", "vendas", "contato", "atendimento", "marketing", "negocios")


def _page_content(response: httpx.Response) -> tuple[BeautifulSoup, str]:
    html = response.text[:2_000_000]
    soup = BeautifulSoup(html, "html.parser")
    searchable = " ".join(
        [html, soup.get_text(" ", strip=True)]
        + [tag.get("src", "") for tag in soup.find_all(src=True)]
        + [tag.get("href", "") for tag in soup.find_all(href=True)]
    ).lower()
    return soup, searchable


def _public_emails(searchable: str, domain: str) -> list[str]:
    emails = {
        email.lower().strip(".,;:()[]<>")
        for email in EMAIL_RE.findall(searchable)
        if not any(part in email.lower() for part in IGNORED_EMAIL_PARTS)
    }
    business_emails = [email for email in emails if email.rsplit("@", 1)[-1] not in FREE_EMAIL_DOMAINS]
    return sorted(business_emails, key=lambda email: _email_priority(email, domain))


def is_business_email(email: str | None) -> bool:
    return bool(email and "@" in email and email.rsplit("@", 1)[-1].lower() not in FREE_EMAIL_DOMAINS)


def _email_priority(email: str, domain: str) -> tuple[int, int, str]:
    local_part, email_domain = email.rsplit("@", 1)
    same_domain = email_domain == domain or domain.endswith("." + email_domain) or email_domain.endswith("." + domain)
    role_account = any(local_part == prefix or local_part.startswith(prefix + ".") for prefix in BUSINESS_EMAIL_PREFIXES)
    return (0 if same_domain else 1, 0 if role_account else 1, email)


def _normalize_br_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    if len(digits) in {10, 11}:
        digits = "55" + digits
    if len(digits) not in {12, 13} or not digits.startswith("55"):
        return None
    return "+" + digits


def _public_phones(soup: BeautifulSoup) -> tuple[list[str], list[str]]:
    phones: set[str] = set()
    whatsapps: set[str] = set()
    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "").strip()
        if href.lower().startswith("tel:"):
            phone = _normalize_br_phone(href[4:])
            if phone:
                phones.add(phone)
        parsed = urlparse(href)
        hostname = (parsed.hostname or "").lower()
        if hostname == "wa.me" or hostname.endswith("whatsapp.com"):
            raw_phone = parsed.path.strip("/") if hostname == "wa.me" else parse_qs(parsed.query).get("phone", [""])[0]
            phone = _normalize_br_phone(raw_phone)
            if phone:
                whatsapps.add(phone)
    if not phones:
        for match in PHONE_RE.findall(soup.get_text(" ", strip=True)):
            phone = _normalize_br_phone(match)
            if phone:
                phones.add(phone)
    return sorted(phones), sorted(whatsapps)


def _contact_links(soup: BeautifulSoup, base_url: str, domain: str) -> list[str]:
    links: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "")
        label = f"{tag.get_text(' ', strip=True)} {href}".lower()
        url = urljoin(base_url, href).split("#", 1)[0]
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {domain, f"www.{domain}"}:
            continue
        if any(term in label for term in CONTACT_TERMS) and url not in links:
            links.append(url)
    return links[:4]


async def scan_domain(domain: str, settings: Settings) -> dict:
    headers = {"User-Agent": settings.crawler_user_agent}
    evidence: list[dict] = []
    found_emails: set[str] = set()
    found_phones: set[str] = set()
    found_whatsapps: set[str] = set()
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, follow_redirects=True, headers=headers) as client:
            homepage = await client.get(f"https://{domain}")
            homepage.raise_for_status()
            home_soup, _ = _page_content(homepage)
            urls = [str(homepage.url), *_contact_links(home_soup, str(homepage.url), domain)]
            responses = [homepage]
            for url in urls[1:]:
                try:
                    page = await client.get(url)
                    page.raise_for_status()
                    if "text/html" in page.headers.get("content-type", "text/html"):
                        responses.append(page)
                except httpx.HTTPError:
                    continue
        scores: dict[str, int] = {}
        for response in responses:
            soup, searchable = _page_content(response)
            found_emails.update(_public_emails(searchable, domain))
            phones, whatsapps = _public_phones(soup)
            found_phones.update(phones)
            found_whatsapps.update(whatsapps)
            for technology, patterns in TECH_SIGNATURES.items():
                matches = sorted({pattern for pattern in patterns if re.search(pattern, searchable, re.I)})
                if matches:
                    scores[technology] = scores.get(technology, 0) + len(matches)
                    evidence.append({"source": str(response.url), "technology": technology, "signatures": matches})
        if not scores:
            return {"crm": None, "confidence": 0.0, "evidence": [], "public_emails": sorted(found_emails), "public_phones": sorted(found_phones), "public_whatsapps": sorted(found_whatsapps), "pages_scanned": len(responses)}
        crm = max(scores, key=scores.get)
        confidence = min(0.95, 0.55 + 0.15 * (scores[crm] - 1))
        return {
            "crm": crm,
            "confidence": confidence,
            "evidence": [item for item in evidence if item["technology"] == crm],
            "public_emails": sorted(found_emails),
            "public_phones": sorted(found_phones),
            "public_whatsapps": sorted(found_whatsapps),
            "pages_scanned": len(responses),
        }
    except (httpx.HTTPError, ValueError):
        return {"crm": None, "confidence": 0.0, "evidence": [], "public_emails": [], "public_phones": [], "public_whatsapps": [], "pages_scanned": 0}


def calculate_lead_score(lead: Lead) -> tuple[int, str, list[str]]:
    score = 0
    reasons: list[str] = []
    if lead.crm:
        points = 50 if lead.confidence >= 0.7 else 35
        score += points
        reasons.append(f"+{points}: CRM {lead.crm} detectado com confiança {lead.confidence:.0%}")
    else:
        reasons.append("+0: nenhum CRM confirmado")
    evidence_pages = len({item.get("source") for item in (lead.evidence or []) if item.get("source")})
    if evidence_pages > 1:
        points = min(20, (evidence_pages - 1) * 10)
        score += points
        reasons.append(f"+{points}: evidência encontrada em {evidence_pages} páginas")
    if getattr(lead, "contact_email", None) or getattr(lead, "contact_whatsapp", None) or getattr(lead, "contact_phone", None):
        score += 20
        reasons.append("+20: canal de contato público disponível")
    if lead.company_name:
        score += 5
        reasons.append("+5: empresa identificada")
    if lead.sector:
        score += 5
        reasons.append("+5: setor identificado")
    score = min(100, score)
    temperature = "hot" if score >= 70 else "warm" if score >= 45 else "cold"
    return score, temperature, reasons


def refresh_lead_score(lead: Lead) -> None:
    lead.lead_score, lead.temperature, lead.score_reasons = calculate_lead_score(lead)


async def enrich_with_hunter(lead: Lead, settings: Settings) -> dict:
    if not settings.hunter_api_key:
        scan = await scan_domain(lead.domain, settings)
        emails = scan["public_emails"]
        if emails and not lead.contact_email:
            lead.contact_email = emails[0]
            return {"provider": "public_site", "status": "found", "email": emails[0]}
        return {"provider": "public_site", "status": "not_found"}
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
