import logging
import requests
from datetime import date, datetime, timedelta
from retriever.models import JobOffer
from retriever.sources.base import Source
from retriever.filters import is_english

logger = logging.getLogger(__name__)

_API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveSource(Source):
    def fetch(self, query: str, days: int) -> list[JobOffer]:
        try:
            resp = requests.get(_API_URL, params={"search": query, "limit": 100}, timeout=10)
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])
        except Exception as e:
            logger.warning("Remotive fetch failed: %s", e)
            return []

        cutoff = datetime.now() - timedelta(days=days)
        results = []

        for item in jobs:
            pub = item.get("publication_date", "")
            try:
                posted = datetime.fromisoformat(pub)
            except (ValueError, AttributeError):
                continue
            if posted < cutoff:
                continue
            title = item.get("title", "")
            if not is_english(title):
                continue
            results.append(JobOffer(
                title=title,
                company=item.get("company_name", ""),
                location=item.get("candidate_required_location", "Remote"),
                url=item.get("url", ""),
                source="remotive",
                posted_at=posted.date(),
            ))

        return results
