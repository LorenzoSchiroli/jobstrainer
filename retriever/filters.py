def is_english(text: str) -> bool:
    if not text:
        return True
    import unicodedata
    for c in text:
        if ord(c) >= 128:
            # Check if it's a Latin letter with diacritical marks (typical of non-English)
            # These are in the range U+0100-U+017F (Latin Extended-A) and similar
            if unicodedata.category(c) in ('Ll', 'Lu', 'Lt') and ord(c) < 0x250:
                # Latin letters with accents
                if any(accent in unicodedata.name(c, '') for accent in ['WITH', 'ACUTE', 'GRAVE', 'DIAERESIS', 'CIRCUMFLEX']):
                    return False
    return True
