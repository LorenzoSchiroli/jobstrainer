import logging
import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def is_english(text: str) -> bool:
    if not text:
        return True
    import unicodedata
    for c in text:
        if ord(c) >= 128:
            if unicodedata.category(c) in ('Ll', 'Lu', 'Lt') and ord(c) < 0x250:
                if any(accent in unicodedata.name(c, '') for accent in ['WITH', 'ACUTE', 'GRAVE', 'DIAERESIS', 'CIRCUMFLEX']):
                    return False
    return True


def _strip_html(html: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def _fetch_description_from_url(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        return _strip_html(resp.text) or None
    except Exception as e:
        logger.debug("Failed to fetch description from %s: %s", url, e)
        return None
