from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .config import Settings
from .google_places import GooglePlacesError, search_google_places
from .services import scan_domain


CATALOG_PATH = Path(__file__).parent / "data" / "private_schools_2025.jsonl.gz"
INEP_SOURCE_URL = "https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/microdados/censo-escolar"
PRIVATE_CATEGORY_LABELS = {
    "1": "particular",
    "2": "comunitaria",
    "3": "confessional",
    "4": "filantropica",
}


def _ascii(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return normalized.encode("ascii", "ignore").decode("ascii").casefold().strip()


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _phone(value: str | None) -> str | None:
    digits = _digits(value)
    if digits.startswith("55") and len(digits) in {12, 13}:
        return f"+{digits}"
    if len(digits) in {10, 11}:
        return f"+55{digits}"
    return None


def _email(value: str | None) -> str | None:
    candidate = (value or "").strip().lower()
    return candidate if "@" in candidate and "." in candidate.rsplit("@", 1)[-1] else None


def _school_quality(school: dict) -> tuple[int, str]:
    score = 0
    score += 5 if school.get("cnpj") else 0
    score += 4 if school.get("has_social_media") else 0
    score += 3 if school.get("has_admin_internet") else 0
    score += 2 if school.get("has_broadband") else 0
    score += 2 if int(school.get("management_staff") or 0) > 0 else 0
    score += 1 if int(school.get("administrative_staff") or 0) > 0 else 0
    stable_key = hashlib.sha1(school["school_code"].encode()).hexdigest()
    return score, stable_key


@lru_cache(maxsize=1)
def load_school_catalog() -> tuple[dict, ...]:
    with gzip.open(CATALOG_PATH, "rt", encoding="utf-8") as source:
        schools = [json.loads(line) for line in source if line.strip()]
    # Hash ordering distributes each daily batch across Brazil instead of
    # exhausting one state before moving to the next.
    schools.sort(key=lambda item: hashlib.sha1(item["school_code"].encode()).hexdigest())
    return tuple(schools)


def select_schools(
    *,
    existing_external_ids: set[str],
    states: list[str],
    cities: list[str],
    private_category: str,
    require_phone: bool,
    limit: int,
) -> list[dict]:
    wanted_states = {state.upper() for state in states}
    wanted_cities = {_ascii(city) for city in cities}
    selected: list[dict] = []
    pool_limit = max(limit, min(1000, limit * 5))
    for school in load_school_catalog():
        external_id = f"inep:{school['school_code']}"
        if external_id in existing_external_ids:
            continue
        if wanted_states and school["state"].upper() not in wanted_states:
            continue
        if wanted_cities and _ascii(school["city"]) not in wanted_cities:
            continue
        if private_category != "all" and school["private_category"] != private_category:
            continue
        normalized_phone = _phone(school.get("phone"))
        if require_phone and not normalized_phone:
            continue
        selected.append({**school, "phone": normalized_phone})
        if len(selected) >= pool_limit:
            break
    selected.sort(key=_school_quality, reverse=True)
    return selected[:limit]


def _best_responsible(qsa: list[dict]) -> tuple[str | None, str | None]:
    priorities = ("administrador", "presidente", "titular", "diretor", "socio")
    candidates = []
    for person in qsa or []:
        name = (person.get("nome_socio") or "").strip()
        role = (person.get("qualificacao_socio") or "").strip()
        if not name:
            continue
        normalized_role = _ascii(role)
        priority = next((index for index, term in enumerate(priorities) if term in normalized_role), len(priorities))
        candidates.append((priority, name, role))
    if not candidates:
        return None, None
    _, name, role = min(candidates)
    return name.title(), role or None


async def fetch_cnpj(cnpj: str, settings: Settings) -> dict:
    timeout = min(6.0, max(3.0, float(settings.request_timeout_seconds)))
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}")
            response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return {"registry_checked": False}
    responsible, role = _best_responsible(payload.get("qsa") or [])
    status = _ascii(payload.get("descricao_situacao_cadastral"))
    return {
        "registry_checked": True,
        "registry_active": status == "ativa",
        "registry_status": payload.get("descricao_situacao_cadastral"),
        "contact_email": _email(payload.get("email")),
        "contact_phone": _phone(payload.get("ddd_telefone_1")) or _phone(payload.get("ddd_telefone_2")),
        "contact_name": responsible,
        "contact_role": role,
        "company_size": payload.get("porte"),
        "legal_name": payload.get("razao_social"),
        "trade_name": payload.get("nome_fantasia"),
        "primary_activity": payload.get("cnae_fiscal_descricao"),
    }


async def enrich_school_batch(schools: list[dict], settings: Settings, limit: int) -> list[dict]:
    if limit <= 0:
        return schools
    semaphore = asyncio.Semaphore(6)
    targets = [school for school in schools if school.get("cnpj")][:limit]

    async def enrich(school: dict) -> tuple[str, dict]:
        async with semaphore:
            result = await fetch_cnpj(school["cnpj"], settings)
        return school["school_code"], result

    tasks = [asyncio.create_task(enrich(school)) for school in targets]
    done, pending = await asyncio.wait(tasks, timeout=14)
    for task in pending:
        task.cancel()
    results: dict[str, dict] = {}
    for task in done:
        try:
            code, result = task.result()
            results[code] = result
        except Exception:
            continue
    return [{**school, **results.get(school["school_code"], {"registry_checked": False})} for school in schools]


def _school_place_match(school: dict, place: dict) -> bool:
    stop_words = {"escola", "colegio", "centro", "educacional", "instituto", "de", "da", "do", "das", "dos"}
    expected = {token for token in re.findall(r"[a-z0-9]+", _ascii(school.get("school_name"))) if token not in stop_words}
    found = {token for token in re.findall(r"[a-z0-9]+", _ascii(place.get("name"))) if token not in stop_words}
    return bool(expected & found) if expected else bool(found)


async def enrich_school_public_contacts(
    schools: list[dict],
    settings: Settings,
    limit: int,
) -> list[dict]:
    """Usa Maps para localizar site/telefone e confirma WhatsApp no site oficial."""
    if limit <= 0 or not (settings.google_maps_api_key or "").strip():
        return schools
    semaphore = asyncio.Semaphore(4)
    targets = schools[:limit]

    async def enrich(school: dict) -> tuple[str, dict]:
        async with semaphore:
            query = f"{school['school_name']} {school['city']} {school['state']}"
            try:
                payload = await search_google_places(
                    query,
                    settings,
                    limit=3,
                    include_contacts=True,
                    include_reviews=False,
                )
            except GooglePlacesError:
                return school["school_code"], {"maps_checked": False}
            place = next((
                item for item in (payload.get("places") or [])
                if item.get("business_status") in {None, "OPERATIONAL"}
                and _school_place_match(school, item)
            ), None)
            if not place:
                return school["school_code"], {"maps_checked": True}
            result = {
                "maps_checked": True,
                "google_place_id": place.get("place_id"),
                "google_maps_url": place.get("google_maps_url"),
                "website_url": place.get("website"),
                "contact_phone": _phone(place.get("phone")),
                "maps_name": place.get("name"),
                "maps_address": place.get("address"),
            }
            website = place.get("website")
            host = (urlparse(website or "").hostname or "").lower().removeprefix("www.")
            if not host or "." not in host:
                return school["school_code"], result
            try:
                site = await asyncio.wait_for(
                    scan_domain(host, settings, max_pages=2),
                    timeout=12,
                )
            except Exception:
                return school["school_code"], result
            result["website_domain"] = host
            result["contact_whatsapp"] = next(iter(site.get("public_whatsapps") or []), None)
            result["website_phone"] = next(iter(site.get("public_phones") or []), None)
            result["website_email"] = next(iter(site.get("public_emails") or []), None)
            result["contact_phone"] = result["contact_phone"] or result["website_phone"]
            result["contact_email"] = result["website_email"]
            return school["school_code"], result

    tasks = [asyncio.create_task(enrich(school)) for school in targets]
    done, pending = await asyncio.wait(tasks, timeout=38)
    for task in pending:
        task.cancel()
    results: dict[str, dict] = {}
    for task in done:
        try:
            code, result = task.result()
            results[code] = result
        except Exception:
            continue
    return [{**school, **results.get(school["school_code"], {})} for school in schools]


def school_evidence(school: dict) -> list[dict]:
    evidence = [{
        "source": INEP_SOURCE_URL,
        "technology": "Censo Escolar INEP 2025",
        "type": "official_school_registry",
        "school_code": school["school_code"],
        "active": True,
        "administrative_category": "privada",
        "private_category": PRIVATE_CATEGORY_LABELS.get(school["private_category"], school["private_category"]),
        "census_year": school["census_year"],
        "public_phone": school.get("phone"),
        "has_social_media": bool(school.get("has_social_media")),
        "has_admin_internet": bool(school.get("has_admin_internet")),
        "has_broadband": bool(school.get("has_broadband")),
    }]
    if school.get("registry_checked"):
        evidence.append({
            "source": f"https://brasilapi.com.br/api/cnpj/v1/{school['cnpj']}",
            "technology": "Cadastro Nacional da Pessoa Juridica",
            "type": "public_company_registry",
            "active": bool(school.get("registry_active")),
            "status": school.get("registry_status"),
            "public_email": school.get("contact_email"),
            "public_phone": school.get("contact_phone"),
            "responsible": school.get("contact_name"),
        })
    if school.get("maps_checked") and school.get("google_place_id"):
        evidence.append({
            "source": school.get("google_maps_url"),
            "technology": "Perfil público no Google Maps",
            "type": "public_business_profile",
            "place_id": school.get("google_place_id"),
            "matched_name": school.get("maps_name"),
            "public_phone": school.get("contact_phone"),
            "website": school.get("website_url"),
        })
    if school.get("contact_whatsapp") and school.get("website_url"):
        evidence.append({
            "source": school.get("website_url"),
            "technology": "Site oficial da escola",
            "type": "official_whatsapp_link",
            "public_whatsapp": school.get("contact_whatsapp"),
        })
    return evidence
