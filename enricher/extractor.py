import json
import logging
from bs4 import BeautifulSoup
from groq import Groq

logger = logging.getLogger(__name__)

_ORG_TYPES = ("Organization", "LocalBusiness", "Corporation")

_LLM_PROMPT = (
    "Extract company information from the following web page text. "
    "Return ONLY valid JSON with exactly these fields (use null if unknown):\n"
    '{{"website": str, "country": str, "founded_year": int, "employee_count": str, '
    '"industry": str, "company_type": "consulting"|"saas"|"product"|"agency"|"startup"|"enterprise"|"ngo"|"other", '
    '"review_score": float, "review_count": int, "description": str}}\n\n'
    "Company name: {name}\n"
    "Location hint: {location}\n\n"
    "Page text:\n{text}"
)


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


def extract_with_llm(html: str, name: str, location: str, client: Groq) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)[:3000]

    prompt = _LLM_PROMPT.format(name=name, location=location, text=text)

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()

        if raw.startswith("```"):
            parts = raw.split("```")
            if len(parts) > 1:
                lines = parts[1].splitlines()
                raw = "\n".join(lines[1:]).strip()

        return json.loads(raw)
    except Exception as e:
        logger.warning("LLM extraction failed: %s", e)
        return {}
