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
