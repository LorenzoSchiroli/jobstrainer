import logging
import os
import re
from groq import Groq

from ingestion.offer.models import OfferExtraction
from ingestion.offer.scraping.models import JobOffer
from ingestion.utils.text import MAX_OFFER_DESCRIPTION_CHARS

logger = logging.getLogger(__name__)

_LLM_PROMPT = (
    "Extract job offer details from the text below. "
    "Return ONLY valid JSON with exactly these fields:\n"
    '{{"employment_type": str|null, "location_type": str|null, "office": str|null, "seniority": str|null, '
    '"salary_range": str|null, "languages_required": list, "text_language": str, '
    '"summary": {{"role_info": list, "requirements": list, "responsibilities": list, "domain": list}}}}\n\n'
    "IMPORTANT: summary contains four lists of short strings (keywords or brief phrases, not full sentences):\n"
    "  role_info: key facts about the role itself (e.g. team size, reporting line, contract type hints).\n"
    "  requirements: required skills, technologies, qualifications, and years of experience.\n"
    "  responsibilities: main tasks and duties of the role.\n"
    "  domain: business or technical domains the role operates in (e.g. 'fintech', 'machine learning', 'e-commerce'). Keep this short — 1 to 3 items.\n"
    "Each list item must be a short phrase. Never use null for any summary list — use [] if nothing applies.\n"
    "CRITICAL: when a value is unknown or not applicable, use JSON null (no quotes) — NEVER the string \"null\".\n"
    "IMPORTANT: text_language is the main language the offer is written in (e.g. \"english\", \"french\"). "
    "Detect it from the text — NEVER return null for this field.\n"
    "IMPORTANT: seniority values: junior, mid, senior, lead, principal, staff, director. "
    "Check the job title first — words like Senior, Junior, Lead, Principal, Staff, Director are direct signals. "
    "Also infer from years of experience required (0-2y → junior, 3-5y → mid, 5+y → senior). "
    "Use null only if there is truly no signal.\n"
    "IMPORTANT: employment_type values: full-time, part-time, contract, internship, stage, freelance. "
    "If the role is a standard permanent position with no indication of contract, part-time, or temporary work, infer full-time. "
    "Use null only if the type is genuinely ambiguous.\n"
    "IMPORTANT: location_type values: on-site, remote, hybrid. "
    "If only an office city is mentioned without specifying remote or hybrid, assume on-site.\n"
    "IMPORTANT: office must be a short city name or address (e.g. \"berlin\", \"london, canary wharf\"). "
    "Only populate when location_type is on-site or hybrid. Never write a sentence or explanation — use null instead.\n"
    "IMPORTANT: languages_required is a list of HUMAN SPOKEN languages required for the role (e.g. 'english', 'french', 'german'). "
    "Never include programming languages, frameworks, or tools — only natural spoken languages. "
    "Include languages explicitly required in the qualifications. "
    "Also include the language the description is written in if it is not English, as it implies that language is needed. "
    "Return an empty list [] if no language requirement can be identified — never null.\n"
    "IMPORTANT: salary_range is the salary exactly as stated in the offer (e.g. '€50,000–€70,000/year'). "
    "Use null if not stated.\n"
    "IMPORTANT: All string values must be lowercase.\n\n"
    "Job title: {title}\n"
    "Job description:\n{description}"
)

_MODEL = os.environ["GROQ_MODEL_BASE"]


def _strip_markdown_json(text: str) -> str:
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    return re.sub(r"\n?```\s*$", "", stripped).strip()


def extract_with_llm(offer: JobOffer, client: Groq) -> OfferExtraction:
    prompt = _LLM_PROMPT.format(
        title=offer.title,
        description=(offer.description or "")[:MAX_OFFER_DESCRIPTION_CHARS],
    )
    try:
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = _strip_markdown_json(response.choices[0].message.content)
        return OfferExtraction.model_validate_json(content)
    except Exception as e:
        logger.warning("LLM extraction failed: %s", e)
        return OfferExtraction()
