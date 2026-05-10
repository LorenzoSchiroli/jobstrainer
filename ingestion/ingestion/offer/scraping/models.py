from dataclasses import dataclass
from datetime import datetime


@dataclass
class JobOffer:
    title: str
    company: str
    location: str
    url: str
    source: str
    posted_at: datetime | None
    description: str | None = None
