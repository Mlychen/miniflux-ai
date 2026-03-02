import re


_RE_SPACE = re.compile(r"\s+")
_RE_URL = re.compile(r"https?://\S+")
_RE_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_RE_LONG_HEX = re.compile(r"\b[0-9a-fA-F]{16,}\b")
_RE_NUMBER = re.compile(r"\b\d+\b")


def normalize_error_key(error: str) -> str:
    text = str(error or "").strip().lower()
    if not text:
        return "(empty)"

    text = text.replace("\r", " ").replace("\n", " ")
    text = _RE_URL.sub("<url>", text)
    text = _RE_UUID.sub("<uuid>", text)
    text = _RE_LONG_HEX.sub("<hex>", text)
    text = _RE_NUMBER.sub("<num>", text)
    text = _RE_SPACE.sub(" ", text).strip()

    if not text:
        return "(empty)"
    return text[:256]
