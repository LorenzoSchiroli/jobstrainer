import os
import requests
from ingestion.offer.models import EnrichedOffer


def _base() -> str:
    return os.environ["BACKEND_URL"].rstrip("/")


def post_job(offer: EnrichedOffer) -> tuple[int, dict]:
    payload = offer.model_dump(mode="json")
    payload["company_name"] = payload.pop("company")
    resp = requests.post(f"{_base()}/jobs", json=payload)
    resp.raise_for_status()
    return resp.status_code, resp.json()


def post_company(data: dict) -> tuple[int, dict]:
    resp = requests.post(f"{_base()}/companies", json=data)
    resp.raise_for_status()
    return resp.status_code, resp.json()
