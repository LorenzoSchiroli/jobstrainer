from abc import ABC, abstractmethod
from retriever.models import JobOffer


class Source(ABC):
    @abstractmethod
    def fetch(self, query: str, days: int) -> list[JobOffer]:
        """Return offers matching query posted within the last `days` days. Never raises — return [] on failure."""
