import logging
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


_RELEVANT_PATHS = {
    # English
    "about", "team", "company", "story", "mission", "people", "who", "culture",
    # German
    "uber-uns", "ueber-uns", "unternehmen", "geschichte", "wir",
    # French
    "a-propos", "apropos", "qui-sommes-nous", "entreprise", "equipe", "societe",
    # Spanish
    "quienes-somos", "sobre-nosotros", "nosotros", "empresa", "equipo",
    # Italian
    "chi-siamo", "azienda", "squadra",
    # Portuguese
    "quem-somos", "sobre-nos",
    # Dutch
    "over-ons", "bedrijf",
}


def find_relevant_links(html: str, base_url: str, max_links: int = 3) -> list[str]:
    base_netloc = urlparse(base_url).netloc
    seen, links = set(), []
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        url = urljoin(base_url, a["href"].strip())
        parsed = urlparse(url)
        if parsed.netloc != base_netloc:
            continue
        path = parsed.path.lower().strip("/")
        if any(kw in path for kw in _RELEVANT_PATHS) and url not in seen:
            seen.add(url)
            links.append(url)
            if len(links) >= max_links:
                break
    return links


_CHALLENGE_MARKERS = ("Just a moment", "Enable JavaScript and cookies", "Checking your browser")


def _is_challenge(html: str) -> bool:
    return any(marker in html for marker in _CHALLENGE_MARKERS)


def fetch_html(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        if resp.status_code == 200 and not _is_challenge(resp.text):
            return resp.text
        logger.debug("requests got %s or challenge for %s, falling back to Playwright", resp.status_code, url)
    except Exception as e:
        logger.debug("requests failed for %s: %s", url, e)
    return _fetch_with_playwright(url)


def _fetch_with_playwright(url: str) -> str | None:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, timeout=15000)
                html = page.content()
            finally:
                browser.close()
            return html
    except Exception as e:
        logger.warning("Playwright failed for %s: %s", url, e)
        return None
