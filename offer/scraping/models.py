from dataclasses import dataclass, field
from datetime import date


@dataclass
class JobOffer:
    title: str
    company: str
    location: str
    url: str
    source: str
    posted_at: date | None
    description: str | None = None
