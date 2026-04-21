import logging
import time
import requests
from datetime import date
from retriever.models import JobOffer
from retriever.sources.base import Source
from retriever.filters import is_english

logger = logging.getLogger(__name__)

_API_URL = "https://arbeitnow.com/api/job-board-api"


class ArbeitnowSource(Source):
    def fetch(self, query: str, days: int) -> list[JobOffer]:
        try:
            resp = requests.get(_API_URL, timeout=10)
            resp.raise_for_status()
            data = resp.json().get("data", [])
        except Exception as e:
            logger.warning("Arbeitnow fetch failed: %s", e)
            return []

        cutoff = time.time() - days * 24 * 3600
        query_lower = query.lower()
        results = []

        for item in data:
            if item.get("created_at", 0) < cutoff:
                continue
            title = item.get("title", "")
            if query_lower not in title.lower():
                continue
            if not is_english(title):
                continue
            results.append(JobOffer(
                title=title,
                company=item.get("company_name", ""),
                location=item.get("location", ""),
                url=item.get("url", ""),
                source="arbeitnow",
                posted_at=date.fromtimestamp(item["created_at"]) if item.get("created_at") else None,
            ))

        return results
