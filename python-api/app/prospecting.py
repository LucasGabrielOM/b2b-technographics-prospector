import asyncio
import json
import math
import re
import unicodedata
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup
from openai import OpenAI

from .config import Settings


PAIN_TERMS = {
    "demora": 18,
    "sem retorno": 22,
    "nao responde": 22,
    "falta de retorno": 25,
    "espera": 12,
    "atraso": 15,
    "atendimento": 8,
    "agendamento": 10,
    "whatsapp": 8,
    "cancelamento": 10,
    "pos-venda": 12,
    "reclamacao": 16,
    "avaliacao": 10,
}

JOB_TERMS = {
    "vagas": "implantacao de CRM",
    "carreira": "implantacao de CRM",
    "trabalhe conosco": "implantacao de CRM",
    "crm": "otimizacao de CRM",
    "atendimento": "recuperacao de atendimento",
    "suporte": "suporte ao CRM",
    "pos-venda": "suporte ao CRM",
    "pós-venda": "suporte ao CRM",
}

SEGMENT_ALIASES = {
    "imobiliaria": ("estate_agent", "real estate", "imobili"),
    "concessionaria": ("car", "motorcycle", "vehicle", "concession"),
    "loja": ("shop", "store", "retail", "loja"),
    "clinica": ("clinic", "doctors", "dentist", "health", "clinica"),
    "distribuidora": ("wholesale", "distributor", "distribuid"),
}

SC_WIDE_CITIES = (
    "Florianopolis",
    "Joinville",
    "Blumenau",
    "Sao Jose",
    "Chapeco",
    "Itajai",
    "Criciuma",
    "Palhoca",
    "Jaragua do Sul",
    "Lages",
    "Balneario Camboriu",
    "Tubarao",
)

IGNORED_DISCOVERY_DOMAINS = {
    "google.com",
    "google.com.br",
    "maps.google.com",
    "linkedin.com",
    "br.linkedin.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "reclameaqui.com.br",
    "vagas.com.br",
    "indeed.com",
    "infojobs.com.br",
    "gupy.io",
}


def _normalize_ascii(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def normalize_domain(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate.startswith(("http://", "https://")):
        candidate = "https://" + candidate
    host = (urlparse(candidate).hostname or "").lower().removeprefix("www.")
    if not host or "." not in host or host.endswith(("facebook.com", "instagram.com", "linkedin.com", "google.com")):
        return None
    return host


def _prospect_key(item: dict) -> str | None:
    domain = normalize_domain(item.get("domain"))
    if domain:
        return f"d:{domain}"
    company = _normalize_ascii(item.get("company_name") or item.get("company") or "").strip()
    location = _normalize_ascii(item.get("location") or "").strip()
    if company:
        return f"c:{company}:{location}"
    email = _normalize_ascii(item.get("contact_email") or "").strip()
    if email:
        return f"e:{email}"
    return None


def _dedupe_prospects(items: list[dict]) -> list[dict]:
    unique: dict[str, dict] = {}
    for item in items:
        key = _prospect_key(item)
        if not key:
            continue
        current = unique.get(key)
        if current is None:
            unique[key] = item
            continue
        current_has_contact = bool(current.get("contact_whatsapp") or current.get("contact_email") or current.get("contact_phone"))
        item_has_contact = bool(item.get("contact_whatsapp") or item.get("contact_email") or item.get("contact_phone"))
        current_score = int(current.get("lead_score") or current.get("score") or 0)
        item_score = int(item.get("lead_score") or item.get("score") or 0)
        current_pain = int(current.get("pain_score") or 0)
        item_pain = int(item.get("pain_score") or 0)
        if (
            (item_has_contact and not current_has_contact)
            or (item_has_contact == current_has_contact and item_score > current_score)
            or (item_has_contact == current_has_contact and item_score == current_score and item_pain > current_pain)
        ):
            unique[key] = item
    return list(unique.values())


def _osm_query(lat: float, lon: float, limit: int) -> str:
    return f"""
[out:json][timeout:30];
(
  nwr["name"]["website"]["shop"](around:18000,{lat},{lon});
  nwr["name"]["website"]["office"](around:18000,{lat},{lon});
  nwr["name"]["website"]["amenity"](around:18000,{lat},{lon});
  nwr["name"]["contact:website"]["shop"](around:18000,{lat},{lon});
  nwr["name"]["contact:website"]["office"](around:18000,{lat},{lon});
  nwr["name"]["contact:website"]["amenity"](around:18000,{lat},{lon});
);
out tags center {max(limit * 5, 100)};
""".strip()


def _use_statewide_search(city: str, state: str) -> bool:
    city_value = _normalize_ascii(city).strip()
    state_value = _normalize_ascii(state).strip()
    return city_value in {"", "santa catarina", "sc", "estado de santa catarina"} or state_value in {"santa catarina", "sc"}


def _search_locations(city: str, state: str) -> list[str]:
    if _use_statewide_search(city, state):
        return list(SC_WIDE_CITIES)
    return [city]


def _segment_aliases(segments: list[str]) -> list[str]:
    aliases: list[str] = []
    for term in segments:
        normalized = _normalize_ascii(term).strip()
        aliases.extend(SEGMENT_ALIASES.get(normalized, (normalized,)))
    return aliases


def _infer_opportunity_type(text: str) -> str:
    normalized = _normalize_ascii(text)
    if any(term in normalized for term in ("vagas", "carreira", "trabalhe conosco")):
        if "crm" in normalized or "atendimento" in normalized or "suporte" in normalized:
            return "implantacao de CRM"
    if any(term in normalized for term in ("demora", "sem retorno", "reclamacao", "atendimento", "avaliacao")):
        return "recuperacao de atendimento"
    if any(term in normalized for term in ("pos-venda", "suporte")):
        return "suporte ao CRM"
    if "crm" in normalized or any(term in normalized for term in ("bitrix24", "hubspot", "salesforce", "pipedrive", "rd station")):
        return "otimizacao de CRM"
    return "prospecao consultiva"


def _build_signal_queries(company_name: str, domain: str) -> list[str]:
    return [
        f'"{company_name}" site:reclameaqui.com.br',
        f'"{company_name}" ("demora" OR "sem retorno" OR reclamacao OR atendimento OR avaliacao)',
        f'"{company_name}" ("vagas" OR "carreira" OR "trabalhe conosco") (CRM OR atendimento OR suporte OR vendas)',
        f'site:{domain} ("fale conosco" OR contato OR atendimento OR suporte)',
    ]


def _score_signals(results: list[dict]) -> dict:
    raw_score = 0
    best_url = None
    best_score = -1
    opportunity_type = None
    summary = None

    for item in results:
        text = f"{item.get('title', '')} {item.get('snippet', '')}"
        normalized = _normalize_ascii(text)
        pain_points = sum(weight for term, weight in PAIN_TERMS.items() if term in normalized)
        job_points = sum(6 for term in JOB_TERMS if _normalize_ascii(term) in normalized)
        total = pain_points + job_points
        if total <= 0:
            continue
        raw_score += total
        if total > best_score:
            best_score = total
            best_url = item.get("url")
            summary = re.sub(r"\s+", " ", text).strip()[:400] or None
            opportunity_type = _infer_opportunity_type(text)
        if not opportunity_type or opportunity_type == "prospecao consultiva":
            opportunity_type = _infer_opportunity_type(text)

    return {
        "pain_score": min(90, 25 + raw_score) if raw_score else 0,
        "pain_summary": summary,
        "pain_source": best_url,
        "opportunity_type": opportunity_type or "prospecao consultiva",
    }


def _deepseek_client(settings: Settings) -> OpenAI | None:
    if not settings.deepseek_api_key:
        return None
    base_url = (settings.deepseek_api_base_url or "https://api.deepseek.com").rstrip("/")
    return OpenAI(api_key=settings.deepseek_api_key, base_url=base_url)


def _deepseek_qualify(company_name: str, domain: str, payload: dict, settings: Settings) -> dict:
    client = _deepseek_client(settings)
    if client is None:
        return {}
    prompt = f"""Avalie um lead B2B com base somente nos sinais publicos abaixo.

Empresa: {company_name}
Dominio: {domain}
Sinais coletados: {json.dumps(payload, ensure_ascii=False)}

Regras:
- Use somente os sinais informados.
- Retorne JSON valido com as chaves:
  - pain_score: inteiro de 0 a 90
  - opportunity_type: texto curto
  - summary: texto curto e factual
  - hot_reason: texto curto explicando a classificacao
  - confidence: numero entre 0 e 1
- Considere quente quando houver reclamações recorrentes, sinal de vaga relacionada a CRM, suporte, vendas ou dificuldade de atendimento.
- Considere morno quando houver sinais mistos, mas contato publico e alguma dor operacional.
- Considere frio quando faltarem sinais publicos uteis.
"""
    response = client.responses.create(
        model=settings.deepseek_model,
        input=prompt,
        text={"verbosity": "low"},
    )
    try:
        return json.loads(response.output_text)
    except (json.JSONDecodeError, TypeError):
        return {}


async def discover_from_osm(city: str, state: str, segments: list[str], limit: int, settings: Settings) -> list[dict]:
    headers = {"User-Agent": settings.crawler_user_agent}
    timeout = max(30.0, settings.request_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        geo = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": f"{city}, {state}, Brasil", "format": "jsonv2", "limit": 1},
        )
        geo.raise_for_status()
        places = geo.json()
        if not places:
            return []
        lat, lon = float(places[0]["lat"]), float(places[0]["lon"])
        last_error = None
        for endpoint in ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"):
            try:
                response = await client.post(endpoint, content=_osm_query(lat, lon, limit))
                response.raise_for_status()
                break
            except httpx.HTTPError as exc:
                last_error = exc
        else:
            raise last_error or RuntimeError("Overpass unavailable")

    prospects: list[dict] = []
    seen: set[str] = set()
    aliases = _segment_aliases(segments)
    for element in response.json().get("elements", []):
        tags = element.get("tags", {})
        domain = normalize_domain(tags.get("website") or tags.get("contact:website"))
        if not domain or domain in seen:
            continue
        searchable = " ".join(str(tags.get(key, "")) for key in ("name", "shop", "office", "amenity", "description", "brand")).lower()
        segment_match = any(alias in searchable for alias in aliases)
        prospects.append({
            "company_name": tags.get("name") or domain,
            "domain": domain,
            "location": f"{city}/{state}",
            "sector": tags.get("shop") or tags.get("office") or tags.get("amenity"),
            "source": f"https://www.openstreetmap.org/{element.get('type')}/{element.get('id')}",
            "segment_match": segment_match,
        })
        seen.add(domain)
    prospects = _dedupe_prospects(prospects)
    prospects.sort(key=lambda item: (not item["segment_match"], item["company_name"].lower()))
    return prospects[:limit]


async def discover_from_web(city: str, state: str, segments: list[str], limit: int, settings: Settings) -> list[dict]:
    prospects: list[dict] = []
    seen: set[str] = set()
    queries: list[str] = []
    for segment in segments:
        queries.extend([
            f'"{segment}" "{city}" "{state}" site oficial "fale conosco"',
            f'"{segment}" "{city}" "{state}" "contato" "atendimento"',
            f'"{segment}" "{city}" "{state}" "trabalhe conosco"',
        ])
    for query in queries:
        try:
            results = await _search_web(query, settings, limit=6)
        except (httpx.HTTPError, ValueError):
            continue
        for result in results:
            domain = normalize_domain(result["url"])
            if not domain or domain in seen or domain in IGNORED_DISCOVERY_DOMAINS:
                continue
            title = re.split(r"\s+[|–—-]\s+", result["title"], maxsplit=1)[0].strip()
            prospects.append({
                "company_name": title or domain,
                "domain": domain,
                "location": f"{city}/{state}",
                "sector": segment,
                "source": result["url"],
                "segment_match": True,
            })
            seen.add(domain)
            if len(prospects) >= limit:
                return _dedupe_prospects(prospects)[:limit]
    return _dedupe_prospects(prospects)[:limit]


async def discover_businesses(city: str, state: str, segments: list[str], limit: int, settings: Settings) -> list[dict]:
    """Combina cadastro geografico, busca web e varredura por varias cidades de SC."""
    prospects: list[dict] = []
    seen: set[str] = set()
    locations = _search_locations(city, state)
    per_location_limit = max(10, math.ceil(limit / max(1, len(locations))))
    for location_city in locations:
        if len(prospects) >= limit:
            break
        try:
            osm_prospects = await discover_from_osm(location_city, state, segments, per_location_limit, settings)
        except (httpx.HTTPError, ValueError, KeyError):
            osm_prospects = []
        web_prospects = await discover_from_web(location_city, state, segments, per_location_limit, settings)
        for item in [*osm_prospects, *web_prospects]:
            key = _prospect_key(item)
            if not key or key in seen:
                continue
            prospects.append(item)
            seen.add(key)
            if len(prospects) >= limit:
                return _dedupe_prospects(prospects)[:limit]
    return _dedupe_prospects(prospects)[:limit]


def _unwrap_ddg_url(href: str) -> str:
    parsed = urlparse(href)
    if "duckduckgo.com" in (parsed.hostname or ""):
        return unquote(parse_qs(parsed.query).get("uddg", [href])[0])
    return href


async def _search_web(query: str, settings: Settings, limit: int = 5) -> list[dict]:
    headers = {"User-Agent": settings.crawler_user_agent}
    async with httpx.AsyncClient(timeout=max(20.0, settings.request_timeout_seconds), headers=headers, follow_redirects=True) as client:
        if settings.serper_api_key:
            response = await client.post(
                "https://google.serper.dev/search",
                headers={**headers, "X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"},
                json={"q": query, "gl": "br", "hl": "pt-br", "num": limit},
            )
            response.raise_for_status()
            return [
                {"title": item.get("title", ""), "url": item.get("link", ""), "snippet": item.get("snippet", "")}
                for item in response.json().get("organic", [])[:limit]
            ]
        response = await client.get("https://html.duckduckgo.com/html/", params={"q": query, "kl": "br-pt"})
        response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for result in soup.select(".result")[:limit]:
        link = result.select_one(".result__a")
        if not link:
            continue
        results.append({
            "title": link.get_text(" ", strip=True),
            "url": _unwrap_ddg_url(link.get("href", "")),
            "snippet": (result.select_one(".result__snippet") or result).get_text(" ", strip=True),
        })
    return results


async def find_complaint_signals(company_name: str, domain: str, settings: Settings) -> dict:
    queries = _build_signal_queries(company_name, domain)
    collected: list[dict] = []
    for query in queries:
        try:
            results = await _search_web(query, settings, limit=5)
        except (httpx.HTTPError, ValueError):
            continue
        collected.extend(results)
    heuristic = _score_signals(collected)
    ai_result: dict = {}
    if settings.deepseek_api_key and collected:
        ai_result = await asyncio.to_thread(
            _deepseek_qualify,
            company_name,
            domain,
            {"queries": queries, "results": collected[:12], "heuristic": heuristic},
            settings,
        )
    pain_score = max(int(ai_result.get("pain_score") or 0), int(heuristic["pain_score"] or 0))
    opportunity_type = ai_result.get("opportunity_type") or heuristic["opportunity_type"]
    summary = ai_result.get("summary") or heuristic["pain_summary"]
    if ai_result.get("confidence") and pain_score:
        pain_score = min(90, pain_score + 5)
    return {
        "pain_score": pain_score,
        "pain_summary": summary,
        "pain_source": heuristic["pain_source"],
        "opportunity_type": opportunity_type,
        "signal_count": len(collected),
        "signal_snapshot": collected[:3],
    }


async def map_complaints(prospects: list[dict], settings: Settings, enabled: bool) -> list[dict]:
    if not enabled:
        return prospects
    semaphore = asyncio.Semaphore(max(1, settings.discovery_concurrency))

    async def enrich(item: dict) -> dict:
        async with semaphore:
            pain = await find_complaint_signals(item["company_name"], item["domain"], settings)
        return {**item, **pain}

    return list(await asyncio.gather(*(enrich(item) for item in prospects)))
