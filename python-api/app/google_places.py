from __future__ import annotations

from typing import Any

import httpx

from .config import Settings


GOOGLE_PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"


class GooglePlacesError(RuntimeError):
    pass


def places_sku(include_contacts: bool, include_reviews: bool) -> tuple[str, int]:
    if include_reviews:
        return "Text Search Enterprise + Atmosphere", 1_000
    if include_contacts:
        return "Text Search Enterprise", 1_000
    return "Text Search Pro", 5_000


def _review_payload(review: dict[str, Any]) -> dict[str, Any]:
    text = ((review.get("text") or {}).get("text") or "").strip()
    author = (review.get("authorAttribution") or {}).get("displayName")
    return {
        "rating": review.get("rating"),
        "text": text[:500],
        "published": review.get("relativePublishTimeDescription"),
        "publish_time": review.get("publishTime"),
        "author": author,
        "google_maps_url": review.get("googleMapsUri"),
    }


def _place_payload(place: dict[str, Any], include_reviews: bool) -> dict[str, Any]:
    display_name = (place.get("displayName") or {}).get("text")
    return {
        "place_id": place.get("id"),
        "name": display_name,
        "address": place.get("formattedAddress"),
        "business_status": place.get("businessStatus"),
        "primary_type": place.get("primaryType"),
        "phone": place.get("nationalPhoneNumber"),
        "website": place.get("websiteUri"),
        "rating": place.get("rating"),
        "review_count": place.get("userRatingCount"),
        "google_maps_url": place.get("googleMapsUri"),
        "reviews": [
            _review_payload(review)
            for review in (place.get("reviews") or [])[:5]
        ] if include_reviews else [],
    }


async def search_google_places(
    query: str,
    settings: Settings,
    *,
    limit: int = 10,
    include_contacts: bool = False,
    include_reviews: bool = False,
) -> dict[str, Any]:
    api_key = (settings.google_maps_api_key or "").strip()
    if not api_key:
        raise GooglePlacesError(
            "Google Maps ainda não está configurado. Adicione GOOGLE_MAPS_API_KEY no Render."
        )

    requested_limit = min(20, max(1, int(limit)))
    fields = [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.businessStatus",
        "places.primaryType",
        "places.googleMapsUri",
    ]
    if include_contacts or include_reviews:
        fields.extend([
            "places.nationalPhoneNumber",
            "places.websiteUri",
        ])
    if include_reviews:
        fields.extend([
            "places.rating",
            "places.userRatingCount",
            "places.reviews",
        ])

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": ",".join(fields),
    }
    body = {
        "textQuery": query.strip(),
        "pageSize": requested_limit,
        "languageCode": "pt-BR",
        "regionCode": "BR",
    }
    timeout = httpx.Timeout(min(30.0, max(8.0, settings.request_timeout_seconds * 2)))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                GOOGLE_PLACES_TEXT_SEARCH_URL,
                headers=headers,
                json=body,
            )
    except httpx.TimeoutException as exc:
        raise GooglePlacesError("O Google Maps demorou para responder. Tente novamente.") from exc
    except httpx.HTTPError as exc:
        raise GooglePlacesError("Não foi possível conectar ao Google Maps.") from exc

    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message")
        except ValueError:
            detail = None
        raise GooglePlacesError(detail or f"Google Maps retornou erro {response.status_code}.")

    payload = response.json()
    sku, free_cap = places_sku(include_contacts, include_reviews)
    return {
        "query": query.strip(),
        "sku": sku,
        "free_monthly_events": free_cap,
        "review_order": "relevância" if include_reviews else None,
        "places": [
            _place_payload(place, include_reviews)
            for place in (payload.get("places") or [])[:requested_limit]
        ],
    }
