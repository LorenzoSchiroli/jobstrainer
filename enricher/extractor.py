import json
import logging
import re
from bs4 import BeautifulSoup
from groq import Groq

from enricher.models import CompanyExtraction

logger = logging.getLogger(__name__)

_ORG_TYPES = ("Organization", "LocalBusiness", "Corporation")

_LLM_PROMPT = (
    "Extract company information from the sources below. "
    "Return ONLY valid JSON with exactly these fields (use null if unknown):\n"
    '{{"website": str, "country": str, "founded_year": int, "employee_count": str, '
    '"industry": str, "is_consulting": bool, "is_startup": bool, '
    '"review_score": float, "review_count": int, "description": str}}\n\n'
    "IMPORTANT: review_score and review_count refer to Glassdoor EMPLOYEE ratings only "
    "(e.g. '4.1 out of 5 stars based on 35 reviews'). "
    "Ignore any app store, user, or parent ratings from the website. "
    "If review snippets are provided, use them as the authoritative source for review fields.\n"
    "IMPORTANT: employee_count refers to the number of actual employees (full-time or part-time) "
    "working for the company. Do not use counts of platform users, freelancers, contractors, "
    "community members, customers, or any other non-employee group, even if those numbers appear "
    "prominently on the website. If no genuine employee count is available, return null.\n"
    "IMPORTANT: All text fields (description, industry) must be written in English, "
    "even if the source content is in another language.\n\n"
    "IMPORTANT: For is_startup, use conservative inference from available evidence "
    "(company self-description, funding stage, age/size signals). "
    "If evidence is weak or conflicting, return null.\n\n"
    "Company name: {name}\n"
    "Location hint: {location}\n\n"
    "{snippets_section}"
    "Website text:\n{text}"
)

_SNIPPETS_SECTION = "Review snippets (from search results):\n{snippets}\n\n"

_FINANCIAL_PROMPT = (
    "You are a financial analyst. Assess the financial health of the company below "
    "based on the provided sources.\n\n"
    "Return ONLY valid JSON with exactly these fields:\n"
    '{{"score": int, "rationale": str}}\n\n'
    "Score the company 1–5 using these anchors:\n"
    "1 = critical risk (bankruptcy, insolvency, severe losses)\n"
    "2 = financially stressed (significant debt, declining revenue)\n"
    "3 = neutral (stable but no strong signals either way)\n"
    "4 = financially healthy (profitable, growing, solid balance sheet)\n"
    "5 = very healthy (strong profitability, cash-rich, market leader)\n\n"
    "IMPORTANT: Write the rationale in English, 1 sentence, citing the key signal "
    "from the sources (e.g. revenue trend, debt level, profitability). "
    "If signals are too weak to assess confidently, use score 3 and explain the lack of data.\n\n"
    "Company name: {name}\n\n"
    "{snippets_section}"
    "Financial page text:\n{text}"
)

_FINANCIAL_SNIPPETS_SECTION = "Search result snippets:\n{snippets}\n\n"


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
            if desc := data.get("description"):
                result["description"] = desc
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


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def extract_with_llm(
    html: str,
    name: str,
    location: str,
    client: Groq,
    snippets: list[str] | None = None,
    extra_htmls: list[str] | None = None,
    source_url: str | None = None,
) -> CompanyExtraction:
    parts = [_html_to_text(html)]
    for extra in (extra_htmls or []):
        parts.append(_html_to_text(extra))
    text = " ".join(parts)[:8000]

    snippets_section = (
        _SNIPPETS_SECTION.format(snippets="\n".join(f"- {s}" for s in snippets))
        if snippets
        else ""
    )
    prompt = _LLM_PROMPT.format(
        name=name, location=location, snippets_section=snippets_section, text=text
    )

    label = f"Website text ({source_url})" if source_url else "Website text"
    print(prompt.replace("Website text:", f"{label}:", 1))

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


def assess_financial_health(
    html: str | None,
    snippets: list[str],
    name: str,
    client: Groq,
) -> "FinancialHealth | None":
    if html is None and not snippets:
        return None

    from enricher.models import FinancialHealth

    text = _html_to_text(html)[:6000] if html else ""
    snippets_section = (
        _FINANCIAL_SNIPPETS_SECTION.format(snippets="\n".join(f"- {s}" for s in snippets))
        if snippets
        else ""
    )
    prompt = _FINANCIAL_PROMPT.format(name=name, snippets_section=snippets_section, text=text)

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = _strip_markdown_json(response.choices[0].message.content)
        return FinancialHealth.model_validate_json(content)
    except Exception as e:
        logger.warning("Financial health assessment failed: %s", e)
        return None
