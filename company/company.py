import logging
import time
from groq import Groq

from company.models import CompanyProfile
from company.scraping.scraping import scrape, scrape_financial
from company.parsing.parsing import parse, parse_financial

logger = logging.getLogger(__name__)


def enrich(name: str, location: str, client: Groq) -> tuple[CompanyProfile, list[tuple[str, float]]]:
    timings: list[tuple[str, float]] = []

    def tick(label: str, t0: float) -> float:
        timings.append((label, time.perf_counter() - t0))
        return time.perf_counter()

    t = time.perf_counter()
    text_dict = scrape(name, location)
    t = tick("scrape", t)

    info = parse(name, location, text_dict, client)
    t = tick("parse", t)

    if info.registration_numbers and info.financial_health_score in (None, 3):
        financial_text = scrape_financial(name, location, info.registration_numbers)
        t = tick("scrape financial", t)
        info = parse_financial(name, location, info, financial_text, client)
        t = tick("parse financial", t)

    return CompanyProfile.model_validate({"name": name, **info.model_dump()}), timings
