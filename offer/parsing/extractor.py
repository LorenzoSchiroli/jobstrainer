import logging
import re
from groq import Groq

from offer.models import OfferExtraction
from offer.scraping.models import JobOffer

logger = logging.getLogger(__name__)

_LLM_PROMPT = (
    "Extract job offer details from the text below. "
    "Return ONLY valid JSON with exactly these fields (use null if not stated):\n"
    '{{"employment_type": str, "location_type": str, "office": str, "seniority": str, "salary_range": str}}\n\n'
    "IMPORTANT: employment_type values: full-time, part-time, contract, internship, stage, freelance. "
    "Use null if not stated.\n"
    "IMPORTANT: location_type values: on-site, remote, hybrid. "
    "If only an office city is mentioned without specifying remote or hybrid, assume on-site.\n"
    "IMPORTANT: office is the city or address of the office, only when location_type is on-site or hybrid. "
    "Use null if location_type is remote or not stated.\n"
    "IMPORTANT: seniority values: junior, mid, senior, lead, principal, staff, director. "
    "Use null if not explicitly stated or clearly inferable.\n"
    "IMPORTANT: salary_range is the salary exactly as stated in the offer (e.g. '€50,000–€70,000/year'). "
    "Use null if not stated.\n"
    "IMPORTANT: Use null for any field not explicitly stated or clearly inferable from the text.\n"
    "IMPORTANT: All text fields must be in English.\n\n"
    "Job title: {title}\n"
    "Job description:\n{description}"
)


def _strip_markdown_json(text: str) -> str:
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    return re.sub(r"\n?```\s*$", "", stripped).strip()


def extract_with_llm(offer: JobOffer, client: Groq) -> OfferExtraction:
    prompt = _LLM_PROMPT.format(
        title=offer.title,
        description=(offer.description or "")[:8000],
    )
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = _strip_markdown_json(response.choices[0].message.content)
        return OfferExtraction.model_validate_json(content)
    except Exception as e:
        logger.warning("LLM extraction failed: %s", e)
        return OfferExtraction()
