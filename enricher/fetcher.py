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


def fetch_html(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        logger.debug("requests failed for %s: %s", url, e)
    return _fetch_with_playwright(url)


def _fetch_with_playwright(url: str) -> str | None:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=15000)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        logger.warning("Playwright failed for %s: %s", url, e)
        return None
