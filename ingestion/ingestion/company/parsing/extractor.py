import json
import logging
import re
from bs4 import BeautifulSoup
from groq import Groq

from ingestion.company.models import CompanyExtraction
from ingestion.utils.text import MAX_COMPANY_DESCRIPTION_CHARS

logger = logging.getLogger(__name__)

_ORG_TYPES = ("Organization", "LocalBusiness", "Corporation")

_LLM_PROMPT = (
    "Extract company information from the sources below. "
    "Return ONLY valid JSON with exactly these fields (use null if unknown):\n"
    '{{"topic": str, "country": str, "founded_year": int, "employee_count": str, '
    '"industry": str, "is_consulting": bool, "is_startup": bool, '
    '"review_score": float, "review_count": int, '
    '"financial_health_score": int, "financial_health_rationale": str, '
    '"registration_numbers": null}}\n\n'
    "IMPORTANT: topic is a single sentence describing what the company does and its main product or service "
    "(e.g. 'Google is a search engine and technology company', "
    "'Barclays is a British universal bank providing retail and investment banking services'). "
    "Be specific and factual — never generic like 'a company that provides services'.\n"
    "IMPORTANT: review_score and review_count must come from Glassdoor EMPLOYEE ratings only. "
    "Ignore any app store, user, customer, or parent-company ratings. "
    "Prefer the overall company rating (e.g. '4.1 out of 5 stars based on 35 reviews'). "
    "If no overall rating is available, use any Glassdoor employee sub-category rating "
    "(e.g. compensation, work-life balance, senior management) as a best-effort value. "
    "review_score and review_count are independent — extract whichever is available, even if the other is null. "
    "If glassdoor_reviews are provided in the sources, use them as the authoritative source for review fields.\n"
    "IMPORTANT: employee_count refers to the number of actual employees (full-time or part-time) "
    "working for the company. Do not use counts of platform users, freelancers, contractors, "
    "community members, customers, or any other non-employee group, even if those numbers appear "
    "prominently on the website. If no genuine employee count is available, return null.\n"
    "IMPORTANT: All text fields (description, industry, financial_health_rationale) must be written "
    "in English, even if the source content is in another language.\n\n"
    "IMPORTANT: For is_startup, use conservative inference from available evidence "
    "(company self-description, funding stage, age/size signals). "
    "If evidence is weak or conflicting, return null.\n\n"
    "IMPORTANT: For financial_health_score, rate the company's financial health 1–5:\n"
    "1 = critical risk (bankruptcy, insolvency, severe losses)\n"
    "2 = financially stressed (significant debt, declining revenue)\n"
    "3 = neutral (stable but no strong signals either way)\n"
    "4 = financially healthy (profitable, growing, solid balance sheet)\n"
    "5 = very healthy (strong profitability, cash-rich, market leader)\n"
    "financial_health_rationale must be 1 sentence in English citing the key signal "
    "(revenue trend, debt level, funding stage, profitability). "
    "If signals are too weak to assess confidently, use score 3. "
    "If financial_snippets are provided in the sources, use them as the authoritative source for financial fields.\n\n"
    "IMPORTANT: For registration_numbers, extract any official company registration or tax identifiers "
    "found anywhere in the sources (footer, legal/imprint page, about page, contact page). "
    "Only include a key if you found an actual value — omit it entirely if not found (do NOT use 'Not Found', 'N/A', or null as a value). "
    "Recognised types: VAT (EU, e.g. IT12345678901 / DE123456789), "
    "EIN (US, e.g. 12-3456789), "
    "CRN (UK/Ireland, e.g. 12345678), "
    "SIREN or SIRET (France), "
    "HRB or HRA (Germany), "
    "KVK (Netherlands), "
    "CIF or NIF (Spain/Portugal), "
    "DUNS (global). "
    "If none are found, return null.\n\n"
    "Company name: {name}\n"
    "Location hint: {location}\n\n"
    "Sources:\n{sources_json}"
)

def _strip_markdown_json(text: str) -> str:
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    return re.sub(r"\n?```\s*$", "", stripped).strip()


def extract_jsonld(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    result = {}

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = next((d for d in data if d.get("@type") in _ORG_TYPES), {})
            if data.get("@type") not in _ORG_TYPES:
                continue

            if url := data.get("url"):
                result["website"] = url
            if rating := data.get("aggregateRating"):
                try:
                    result["review_score"] = float(rating["ratingValue"])
                    result["review_count"] = int(rating["reviewCount"])
                except (KeyError, ValueError):
                    pass
            if address := data.get("address"):
                if country := address.get("addressCountry"):
                    result["country"] = country
            if employees := data.get("numberOfEmployees"):
                val = employees.get("value") if isinstance(employees, dict) else employees
                if val is not None:
                    result["employee_count"] = str(val)
            if founded := data.get("foundingDate"):
                try:
                    result["founded_year"] = int(str(founded)[:4])
                except ValueError:
                    pass
        except (json.JSONDecodeError, AttributeError):
            continue

    return result


def extract_with_llm(
    name: str,
    location: str,
    client: Groq,
    sources: dict,
) -> CompanyExtraction:
    sources_json = json.dumps(sources, ensure_ascii=False)[:MAX_COMPANY_DESCRIPTION_CHARS]
    prompt = _LLM_PROMPT.format(name=name, location=location, sources_json=sources_json)

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = _strip_markdown_json(response.choices[0].message.content)
        return CompanyExtraction.model_validate_json(content)
    except Exception as e:
        logger.warning("LLM extraction failed: %s", e)
        return CompanyExtraction()
