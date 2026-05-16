import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from ingestion.utils.text import has_text as _has_text_util

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
    "about", "about-us", "company", "team", "story", "our-story", "mission",
    "people", "who-we-are", "who-we", "culture", "overview", "history",
    # German
    "uber-uns", "ueber-uns", "unternehmen", "das-unternehmen", "firma",
    "konzern", "geschichte", "wer-wir-sind", "wir", "team",
    # French
    "a-propos", "apropos", "qui-sommes-nous", "notre-histoire",
    "entreprise", "notre-entreprise", "equipe", "societe",
    # Italian
    "chi-siamo", "azienda", "la-nostra-storia", "squadra", "team",
    # Spanish
    "quienes-somos", "sobre-nosotros", "nosotros", "empresa",
    "nuestra-historia", "equipo",
    # Portuguese
    "quem-somos", "sobre-nos", "a-empresa", "nossa-historia",
    # Dutch
    "over-ons", "wie-zijn-wij", "ons-verhaal", "bedrijf", "organisatie",
    # Danish
    "om-os", "virksomhed", "om-virksomheden", "hvem-er-vi", "hold",
    # Swedish
    "om-oss", "om-foretaget", "foretaget", "vara-tjanster", "vilka-vi-ar",
    # Norwegian
    "om-oss", "om-bedriften", "selskapet", "hvem-er-vi",
    # Finnish
    "meista", "yritys", "tietoa-meista", "keita-olemme",
}


_PROBE_PATHS = [
    # English
    "/about", "/about-us", "/company", "/team", "/our-story",
    "/who-we-are", "/mission", "/culture", "/overview",
    # German
    "/uber-uns", "/ueber-uns", "/unternehmen", "/das-unternehmen",
    "/firma", "/wer-wir-sind",
    # French
    "/a-propos", "/qui-sommes-nous", "/notre-entreprise", "/equipe",
    # Italian
    "/chi-siamo", "/azienda",
    # Spanish
    "/quienes-somos", "/sobre-nosotros", "/nosotros",
    # Portuguese
    "/quem-somos", "/sobre-nos",
    # Dutch
    "/over-ons", "/wie-zijn-wij", "/bedrijf",
    # Danish
    "/om-os", "/virksomhed", "/hvem-er-vi",
    # Swedish
    "/om-oss", "/om-foretaget", "/vilka-vi-ar",
    # Norwegian (shares /om-oss with Swedish)
    "/om-bedriften", "/selskapet",
    # Finnish
    "/meista", "/yritys", "/tietoa-meista",
]


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

    if len(links) < max_links:
        parsed_base = urlparse(base_url)
        root = f"{parsed_base.scheme}://{parsed_base.netloc}"
        candidates = [root + p for p in _PROBE_PATHS if root + p not in seen]

        def _head_ok(url: str) -> str | None:
            try:
                r = requests.head(url, headers=_HEADERS, timeout=2, allow_redirects=True)
                return url if r.status_code == 200 else None
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=len(candidates)) as ex:
            futures = {ex.submit(_head_ok, url): url for url in candidates}
            for fut in as_completed(futures):
                url = fut.result()
                if url and url not in seen:
                    seen.add(url)
                    links.append(url)
                    logger.debug("probed %s → 200", url)
                    if len(links) >= max_links:
                        for f in futures:
                            f.cancel()
                        break

    return links


_CHALLENGE_MARKERS = ("Just a moment", "Enable JavaScript and cookies", "Checking your browser")


def _is_challenge(html: str) -> bool:
    return any(marker in html for marker in _CHALLENGE_MARKERS)


def _has_text(html: str) -> bool:
    return _has_text_util(html)


def fetch_html(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        if resp.status_code == 200 and not _is_challenge(resp.text) and _has_text(resp.text):
            return resp.text
        logger.debug("requests got %s or empty/challenge for %s, falling back to Playwright", resp.status_code, url)
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
