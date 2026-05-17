import os
import requests
from ingestion.offer.models import EnrichedOffer


def _base() -> str:
    url = os.environ.get("BACKEND_URL")
    if not url:
        raise RuntimeError("BACKEND_URL environment variable is not set")
    return url.rstrip("/")


def post_job(offer: EnrichedOffer, embedding: list[float] | None = None) -> tuple[int, dict]:
    payload = offer.model_dump(mode="json")
    payload["company_name"] = payload.pop("company")
    if embedding is not None:
        payload["embedding"] = embedding
    resp = requests.post(f"{_base()}/jobs/", json=payload, timeout=30)
    if not resp.ok:
        raise requests.HTTPError(f"{resp.status_code} — {resp.text}", response=resp)
    return resp.status_code, resp.json()


def post_company(data: dict) -> tuple[int, dict]:
    resp = requests.post(f"{_base()}/companies/", json=data, timeout=30)
    if not resp.ok:
        raise requests.HTTPError(f"{resp.status_code} — {resp.text}", response=resp)
    return resp.status_code, resp.json()
