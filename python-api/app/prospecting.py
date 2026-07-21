import asyncio
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from .config import Settings


PAIN_TERMS = {
    "demora": 18,
    "sem retorno": 22,
    "não responde": 22,
    "nao responde": 22,
    "falta de retorno": 25,
    "espera": 12,
    "atraso": 15,
    "atendimento": 8,
    "agendamento": 10,
    "whatsapp": 8,
    "cancelamento": 10,
    "pós-venda": 12,
    "pos-venda": 12,
}

SEGMENT_ALIASES = {
    "imobiliária": ("estate_agent", "real estate", "imobili"),
    "concessionária": ("car", "motorcycle", "vehicle", "concession"),
    "loja": ("shop", "store", "retail", "loja"),
    "clínica": ("clinic", "doctors", "dentist", "health", "clínica"),
    "distribuidora": ("wholesale", "distributor", "distribuid"),
}


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


def _osm_query(area_id: int, limit: int) -> str:
    return f"""
[out:json][timeout:30];
area({area_id})->.searchArea;
(
  nwr[\"name\"][\"website\"](area.searchArea);
  nwr[\"name\"][\"contact:website\"](area.searchArea);
);
out tags center {max(limit * 5, 100)};
""".strip()


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
        osm_type = places[0].get("osm_type")
        osm_id = int(places[0]["osm_id"])
        area_id = osm_id + (3_600_000_000 if osm_type == "relation" else 2_400_000_000)
        response = await client.post("https://overpass-api.de/api/interpreter", content=_osm_query(area_id, limit))
        response.raise_for_status()

    prospects: list[dict] = []
    seen: set[str] = set()
    for element in response.json().get("elements", []):
        tags = element.get("tags", {})
        domain = normalize_domain(tags.get("website") or tags.get("contact:website"))
        if not domain or domain in seen:
            continue
        searchable = " ".join(str(tags.get(key, "")) for key in ("name", "shop", "office", "amenity", "description", "brand")).lower()
        # Segmentos servem para priorizar, sem eliminar empresas quando o OSM não tem categoria completa.
        aliases = [alias for term in segments for alias in SEGMENT_ALIASES.get(term.strip().lower(), (term.strip().lower(),))]
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
    prospects.sort(key=lambda item: (not item["segment_match"], item["company_name"].lower()))
    return prospects[:limit]


async def discover_businesses(city: str, state: str, segments: list[str], limit: int, settings: Settings) -> list[dict]:
    """Combina cadastro geográfico e busca web; sempre deduplica pelo domínio oficial."""
    try:
        prospects = await discover_from_osm(city, state, segments, limit, settings)
    except (httpx.HTTPError, ValueError, KeyError):
        prospects = []
    seen = {item["domain"] for item in prospects}
    for segment in segments:
        if len(prospects) >= limit:
            break
        try:
            results = await _search_web(f'{segment} em "{city}" "{state}" site oficial', settings, limit=8)
        except (httpx.HTTPError, ValueError):
            continue
        for result in results:
            domain = normalize_domain(result["url"])
            if not domain or domain in seen or "reclameaqui.com.br" in domain:
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
                break
    return prospects[:limit]


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
    query = f'"{company_name}" (demora OR "sem retorno" OR atendimento OR reclamação) site:reclameaqui.com.br'
    try:
        results = await _search_web(query, settings)
    except (httpx.HTTPError, ValueError):
        return {"pain_score": 0, "pain_summary": None, "pain_source": None}
    relevant = []
    total = 0
    for item in results:
        text = f"{item['title']} {item['snippet']}".lower()
        points = sum(weight for term, weight in PAIN_TERMS.items() if term in text)
        if points and "reclameaqui.com.br" in item["url"]:
            relevant.append((item, points))
            total += points
    if not relevant:
        return {"pain_score": 0, "pain_summary": None, "pain_source": None}
    relevant.sort(key=lambda pair: pair[1], reverse=True)
    best = relevant[0][0]
    score = min(90, 30 + total + max(0, len(relevant) - 1) * 10)
    summary = re.sub(r"\s+", " ", best["snippet"]).strip()[:400]
    return {"pain_score": score, "pain_summary": summary, "pain_source": best["url"]}


async def map_complaints(prospects: list[dict], settings: Settings, enabled: bool) -> list[dict]:
    if not enabled:
        return prospects
    semaphore = asyncio.Semaphore(max(1, settings.discovery_concurrency))

    async def enrich(item: dict) -> dict:
        async with semaphore:
            pain = await find_complaint_signals(item["company_name"], item["domain"], settings)
        return {**item, **pain}

    return list(await asyncio.gather(*(enrich(item) for item in prospects)))
