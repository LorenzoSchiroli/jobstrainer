from groq import Groq

from offer.models import OfferExtraction
from offer.parsing.extractor import extract_with_llm
from offer.scraping.models import JobOffer


def parse(offer: JobOffer, client: Groq) -> OfferExtraction:
    if not offer.description:
        return OfferExtraction()
    return extract_with_llm(offer, client)
