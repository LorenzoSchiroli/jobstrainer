from abc import ABC, abstractmethod
from offer.scraping.models import JobOffer


class Source(ABC):
    @abstractmethod
    def fetch(self, query: str, hours: int) -> list[JobOffer]:
        """Return offers matching query posted within the last `hours` hours. Never raises — return [] on failure."""
