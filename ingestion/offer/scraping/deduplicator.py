import re
from ingestion.offer.scraping.models import JobOffer

_PRIORITY = {"jobspy": 0, "adzuna": 1, "arbeitnow": 2, "remotive": 3}


def _url_key(url: str) -> str:
    return url.rstrip("/").split("?")[0].lower()


def _tc_key(title: str, company: str) -> tuple[str, str]:
    clean = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    return clean(title), clean(company)


def deduplicate(offers: list[JobOffer]) -> list[JobOffer]:
    sorted_offers = sorted(offers, key=lambda o: _PRIORITY.get(o.source.split(":")[0], 99))
    seen_urls: set[str] = set()
    seen_tc: set[tuple[str, str]] = set()
    result: list[JobOffer] = []

    for offer in sorted_offers:
        uk = _url_key(offer.url) if offer.url else None
        tk = _tc_key(offer.title, offer.company)

        if uk and uk in seen_urls:
            continue
        if tk in seen_tc:
            continue

        if uk:
            seen_urls.add(uk)
        seen_tc.add(tk)
        result.append(offer)

    return result
