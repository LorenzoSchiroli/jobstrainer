import logging
from datetime import date
import pandas as pd
from jobspy import scrape_jobs
from retriever.models import JobOffer
from retriever.sources.base import Source
from retriever.filters import is_english

logger = logging.getLogger(__name__)


class JobspySource(Source):
    def fetch(self, query: str, days: int) -> list[JobOffer]:
        try:
            df = scrape_jobs(
                site_name=["linkedin", "indeed"],
                search_term=query,
                hours_old=days * 24,
                results_wanted=50,
                country_indeed="UK",
            )
        except Exception as e:
            logger.warning("jobspy fetch failed: %s", e)
            return []

        results = []
        for _, row in df.iterrows():
            title = row.get("title")
            if not title or not isinstance(title, str):
                continue
            if not is_english(title):
                continue
            posted_at: date | None = None
            raw_date = row.get("date_posted")
            if pd.notna(raw_date) and raw_date is not None:
                try:
                    posted_at = pd.Timestamp(raw_date).date()
                except Exception:
                    pass
            site = row.get("site", "unknown")
            results.append(JobOffer(
                title=title,
                company=str(row.get("company") or ""),
                location=str(row.get("location") or ""),
                url=str(row.get("job_url") or ""),
                source=f"jobspy:{site}",
                posted_at=posted_at,
            ))

        return results
