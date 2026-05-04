from dataclasses import dataclass
from datetime import date


@dataclass
class JobOffer:
    title: str
    company: str
    location: str
    url: str
    source: str
    posted_at: date | None
