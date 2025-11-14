import re
import unicodedata


# ---------------------------------------------------------
# UTF-8 / Encoding reparieren (z.B. "RÃ¼ck" → "Rück")
# ---------------------------------------------------------
def fix_encoding(text: str) -> str:
    if not isinstance(text, str):
        return ""
    try:
        return text.encode("latin1").decode("utf8")
    except Exception:
        return text


# ---------------------------------------------------------
# Titel reinigen
# ---------------------------------------------------------
def clean_title(title: str) -> str:
    if not title:
        return ""

    title = fix_encoding(title)

    # (NASDAQ:MSFT), $AAPL etc entfernen
    title = re.sub(r"\([A-Z]{2,10}:[A-Z]{2,10}\)", "", title)
    title = re.sub(r"\$[A-Z]{1,10}", "", title)

    # doppelte spaces
    title = re.sub(r"\s+", " ", title).strip()

    return title


# ---------------------------------------------------------
# Ticker entfernen (für Content)
# ---------------------------------------------------------
def remove_tickers(text: str) -> str:
    if not text:
        return text

    patterns = [
        r"\([A-Z]{2,10}:[A-Z]{2,10}\)",   # (NASDAQ:MSFT)
        r"\$[A-Z]{1,10}",                 # $MSFT
        r"\([A-Z]{2,6}\)",                # (MSFT)
    ]
    for p in patterns:
        text = re.sub(p, "", text)

    return text


# ---------------------------------------------------------
# Newsletter/Boilerplate entfernen
# ---------------------------------------------------------
def remove_boilerplate(text: str) -> str:
    if not text:
        return ""

    boiler_patterns = [
        r"Subscribe to our newsletter.*",
        r"Sign up to receive.*",
        r"Follow us on.*",
        r"Alle Rechte vorbehalten.*",
        r"Hier klicken um mehr zu lesen.*",
        r"Du willst keine News verpassen.*",
    ]

    for bp in boiler_patterns:
        text = re.sub(bp, "", text, flags=re.IGNORECASE)

    return text


# ---------------------------------------------------------
# Whitespace normalisieren
# ---------------------------------------------------------
def normalize_whitespace(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------
# Länge begrenzen (für GPT-mini, sonst langsamer)
# ---------------------------------------------------------
def limit_length(text: str, max_chars: int = 2000) -> str:
    if not text:
        return ""
    return text[:max_chars]


# ---------------------------------------------------------
# Gesamter Text-Cleaner (für AI)
# ---------------------------------------------------------
def clean_text(text: str) -> str:
    if not text:
        return ""

    text = fix_encoding(text)
    text = remove_tickers(text)
    text = remove_boilerplate(text)
    text = normalize_whitespace(text)
    text = limit_length(text)

    return text
