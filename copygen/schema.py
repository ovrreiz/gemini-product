"""Схема відповіді (structured output) і розбір/нормалізація JSON від моделі."""
import json
import re

from .errors import BadResponse
from .models import ProductCopy, clean_text

# Схема для Gemini API (response_schema). Типи пишуться великими літерами, як у документації Google.
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING", "description": "Catchy product title"},
        "short_description": {"type": "STRING", "description": "1-2 sentence summary"},
        "long_description": {"type": "STRING", "description": "Full description, short paragraphs"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"},
                     "description": "Hashtags without spaces, each starting with #"},
        "call_to_action": {"type": "STRING", "description": "One short call to action"},
        "keywords": {"type": "ARRAY", "items": {"type": "STRING"},
                     "description": "3-8 search keywords (SEO)"},
    },
    "required": ["title", "short_description", "long_description", "hashtags", "call_to_action", "keywords"],
}

_NON_WORD = re.compile(r"[^\w]", re.UNICODE)


def normalize_hashtags(tags, limit: int) -> list:
    """'# My tag!' -> '#Mytag'; прибирає дублікати (без урахування регістру) і порожні, обрізає до limit."""
    out, seen = [], set()
    for t in tags or []:
        body = _NON_WORD.sub("", str(t).replace("#", ""))
        if not body:
            continue
        tag = "#" + body
        if tag.lower() in seen:
            continue
        seen.add(tag.lower())
        out.append(tag)
        if len(out) >= limit:
            break
    return out


def _str(d: dict, key: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        raise BadResponse(f"У відповіді моделі відсутнє або порожнє поле «{key}».")
    return clean_text(v)


def _list(d: dict, key: str) -> list:
    v = d.get(key)
    if not isinstance(v, list):
        raise BadResponse(f"Поле «{key}» має бути списком.")
    return [clean_text(str(x)) for x in v if str(x).strip()]


def strip_code_fence(text: str) -> str:
    """Деякі моделі загортають JSON у ```json ... ``` — прибираємо огорожу."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def parse_copy(text: str, tags_limit: int) -> ProductCopy:
    """Рядок JSON -> ProductCopy (з перевіркою полів і нормалізацією хештегів)."""
    try:
        data = json.loads(strip_code_fence(text))
    except (json.JSONDecodeError, TypeError) as e:
        raise BadResponse(f"Відповідь моделі — не коректний JSON ({e}).") from e
    if not isinstance(data, dict):
        raise BadResponse("Відповідь моделі має бути JSON-об'єктом.")
    return ProductCopy(
        title=_str(data, "title"),
        short_description=_str(data, "short_description"),
        long_description=_str(data, "long_description"),
        hashtags=normalize_hashtags(_list(data, "hashtags"), tags_limit),
        call_to_action=_str(data, "call_to_action"),
        keywords=_list(data, "keywords")[:8],
    )
