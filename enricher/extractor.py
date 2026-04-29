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
    '"industry": str, "is_consulting": bool, '
    '"review_score": float, "review_count": int, "description": str}}\n\n'
    "IMPORTANT: review_score and review_count refer to Glassdoor EMPLOYEE ratings only "
    "(e.g. '4.1 out of 5 stars based on 35 reviews'). "
    "Ignore any app store, user, or parent ratings from the website. "
    "If review snippets are provided, use them as the authoritative source for review fields.\n"
    "IMPORTANT: All text fields (description, industry) must be written in English, "
    "even if the source content is in another language.\n\n"
    "Company name: {name}\n"
    "Location hint: {location}\n\n"
    "{snippets_section}"
    "Website text:\n{text}"
)

_SNIPPETS_SECTION = "Review snippets (from search results):\n{snippets}\n\n"


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
