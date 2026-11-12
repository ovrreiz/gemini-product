"""Виклик Gemini API + надійність: повторні спроби, запасні моделі, самовиправлення, кеш, демо-режим.

Уся робота з SDK зосереджена в GeminiBackend — якщо Google змінить SDK/API, правиться лише цей клас.
"""
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, replace

from .checks import feedback_from, run_checks
from .config import PLATFORMS, LANGUAGES, Settings
from .errors import (ApiKeyInvalid, ApiKeyMissing, BackendError, BadResponse, CopygenError, EmptyResponse,
                     ModelUnavailable, QuotaExceeded, ServiceUnavailable)
from .models import GenerationResult, ProductRequest
from .prompts import SYSTEM_INSTRUCTION, build_prompt
from .schema import RESPONSE_SCHEMA, parse_copy


@dataclass
class BackendResponse:
    text: str = None
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = ""


# ------------------------------------------------------------------ реальний бекенд (Gemini API)
class GeminiBackend:
    """Тонка обгортка над офіційним SDK google-genai (імпортується ліниво)."""

    def __init__(self, api_key: str, timeout_s: int = 30):
        self.api_key = api_key
        self.timeout_s = timeout_s
        self._client = None

    def _client_and_types(self):
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise CopygenError("Не встановлено бібліотеку google-genai (pip install -r requirements.txt).") from e
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key,
                                        http_options=types.HttpOptions(timeout=int(self.timeout_s * 1000)))
        return self._client, types

    def generate_json(self, model, system, prompt, temperature, max_tokens) -> BackendResponse:
        client, types = self._client_and_types()
        from google.genai import errors as genai_errors
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=RESPONSE_SCHEMA,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            )
        except genai_errors.APIError as e:
            raise BackendError(int(getattr(e, "code", 0) or 0), str(getattr(e, "message", e)),
                               str(getattr(e, "status", "") or "")) from e
        except Exception as e:  # мережа, таймаут тощо — вважаємо тимчасовою недоступністю
            raise BackendError(503, f"{type(e).__name__}: {e}") from e

        try:
            text = resp.text
        except Exception:
            text = None
        um = getattr(resp, "usage_metadata", None)
        finish = ""
        try:
            finish = str(resp.candidates[0].finish_reason)
        except Exception:
            pass
        return BackendResponse(
            text=text,
            prompt_tokens=int(getattr(um, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(um, "candidates_token_count", 0) or 0),
            total_tokens=int(getattr(um, "total_token_count", 0) or 0),
            finish_reason=finish,
        )


# ------------------------------------------------------------------ демо-бекенд (без API)
_GENERIC_TAGS = {
    "uk": ["новинка", "якість", "рекомендуємо", "вибір", "комфорт", "стиль", "знижки", "україна", "подарунок", "зручно",
           "практично", "топ"],
    "en": ["new", "quality", "recommended", "choice", "comfort", "style", "deal", "gift", "handy", "practical", "top",
           "musthave"],
    "pl": ["nowosc", "jakosc", "polecamy", "wybor", "komfort", "styl", "okazja", "prezent", "praktyczne", "top",
           "hit", "musthave"],
    "de": ["neu", "qualitaet", "empfehlung", "auswahl", "komfort", "stil", "angebot", "geschenk", "praktisch", "top",
           "beliebt", "musthave"],
}
_PHRASES = {
    "uk": {"intro": "Знайомтесь: {name}.", "feats": "Основні характеристики:", "aud": "Для кого: {a}.",
           "cta": "Замовляйте вже сьогодні!"},
    "en": {"intro": "Meet {name}.", "feats": "Key features:", "aud": "Made for: {a}.",
           "cta": "Order yours today!"},
    "pl": {"intro": "Poznaj: {name}.", "feats": "Najwazniejsze cechy:", "aud": "Dla kogo: {a}.",
           "cta": "Zamow juz dzis!"},
    "de": {"intro": "Das ist {name}.", "feats": "Wichtige Merkmale:", "aud": "Fuer wen: {a}.",
           "cta": "Jetzt bestellen!"},
}


def _cut(text: str, n: int) -> str:
    """Обрізає по межі слова до n символів."""
    if len(text) <= n:
        return text
    cut = text[: n - 1].rsplit(" ", 1)[0].rstrip(" ,;:-—")
    return cut or text[: n - 1]


class MockBackend:
    """Детермінований «генератор» без API: показує інтерфейс і працює без ключа. Це НЕ ШІ."""

    def __init__(self, req: ProductRequest):
        self.req = req

    def generate_json(self, model, system, prompt, temperature, max_tokens) -> BackendResponse:
        r, spec = self.req, PLATFORMS[self.req.platform]
        ph = _PHRASES[r.language]
        title = _cut(f"{r.name} — {r.features[0]}", spec.title_max)
        short = _cut(f"{ph['intro'].format(name=r.name)} {r.features[0]}.", spec.short_max)
        lines = [ph["intro"].format(name=r.name), ph["feats"]] + [f"• {f}" for f in r.features]
        if r.audience:
            lines.append(ph["aud"].format(a=r.audience))
        while len("\n".join(lines)) > spec.long_max and len(lines) > 3:
            lines.pop()
        long_ = _cut("\n".join(lines), spec.long_max)
        words = [re.sub(r"\W", "", w) for w in re.findall(r"\w+", f"{r.name} {' '.join(r.features)}")]
        tags = [w for w in words if len(w) >= 4 and not w.isdigit()]
        tags += _GENERIC_TAGS[r.language]
        uniq, seen = [], set()
        for t in tags:
            if t.lower() not in seen:
                seen.add(t.lower())
                uniq.append("#" + t)
        want = max(spec.tags_min, min(spec.tags_max, 5))
        payload = {
            "title": title, "short_description": short, "long_description": long_,
            "hashtags": uniq[:want], "call_to_action": ph["cta"],
            "keywords": [w for w in words if len(w) >= 4][:6] or [r.name],
        }
        return BackendResponse(text=json.dumps(payload, ensure_ascii=False))


# ------------------------------------------------------------------ кеш
_CACHE: "OrderedDict[str, GenerationResult]" = OrderedDict()
CACHE_MAX = 128


def clear_cache() -> None:
    _CACHE.clear()


# ------------------------------------------------------------------ головна функція
def generate(req: ProductRequest, settings: Settings, *, model: str = None, temperature: float = 0.8,
             backend=None, sleep=time.sleep, use_cache: bool = True) -> GenerationResult:
    """Генерує текст для товару. Піднімає CopygenError (повідомлення можна показувати користувачу)."""
    req.validate()
    spec = PLATFORMS[req.platform]
    mock = settings.mock
    if mock:
        backend, order = MockBackend(req), ["demo (без API)"]
    else:
        if backend is None:
            if not settings.has_key:
                raise ApiKeyMissing("Не задано API-ключ Gemini. Введіть його або увімкніть демо-режим.")
            backend = GeminiBackend(settings.api_key, settings.timeout_s)
        preferred = model or settings.models[0]
        order = [preferred] + [m for m in settings.models if m != preferred]

    cache_key = req.cache_key(order[0], temperature)
    if use_cache and not mock and cache_key in _CACHE:
        _CACHE.move_to_end(cache_key)
        return replace(_CACHE[cache_key], from_cache=True, latency_s=0.0)

    counters = {"attempts": 0, "p": 0, "o": 0, "t": 0}

    def ask(model_name: str, prompt: str):
        max_tokens, transient, empty_retry, bad_retry = settings.max_tokens, 0, False, False
        while True:
            counters["attempts"] += 1
            try:
                resp = backend.generate_json(model_name, SYSTEM_INSTRUCTION, prompt, temperature, max_tokens)
            except BackendError as e:
                code, msg = e.code, e.message
                if code in (401, 403) or (code == 400 and "api key" in msg.lower()):
                    raise ApiKeyInvalid("Ключ API не прийнято (невірний, відкликаний або без доступу до моделі).") from e
                if code == 404:
                    raise ModelUnavailable(f"Модель «{model_name}» недоступна (не знайдена або закрита).") from e
                if code in (429, 500, 502, 503, 504):
                    limit = 1 if code == 429 else settings.max_retries
                    if transient < limit:
                        sleep(2 ** transient)
                        transient += 1
                        continue
                    if code == 429:
                        raise QuotaExceeded(f"Ліміт запитів вичерпано для моделі «{model_name}».") from e
                    raise ServiceUnavailable(f"Сервіс тимчасово недоступний (код {code}).") from e
                raise CopygenError(f"Помилка API ({code}): {msg[:300]}") from e
            counters["p"] += resp.prompt_tokens
            counters["o"] += resp.output_tokens
            counters["t"] += resp.total_tokens
            if not resp.text or not resp.text.strip():
                if not empty_retry:
                    empty_retry, max_tokens = True, max_tokens * 2
                    continue
                reason = f" (finish_reason: {resp.finish_reason})" if resp.finish_reason else ""
                raise EmptyResponse("Модель повернула порожню відповідь" + reason + ".")
            try:
                return parse_copy(resp.text, spec.tags_max)
            except BadResponse:
                if not bad_retry:
                    bad_retry = True
                    continue
                raise

    t0 = time.perf_counter()
    seen_errors, copy, used = [], None, None
    for m in order:
        try:
            copy, used = ask(m, build_prompt(req)), m
            break
        except (ModelUnavailable, QuotaExceeded, ServiceUnavailable, EmptyResponse, BadResponse) as e:
            seen_errors.append(e)
    if copy is None:
        for cls in (QuotaExceeded, ServiceUnavailable):
            if any(isinstance(e, cls) for e in seen_errors):
                raise next(e for e in seen_errors if isinstance(e, cls))
        if all(isinstance(e, ModelUnavailable) for e in seen_errors):
            raise ModelUnavailable("Жодна модель зі списку недоступна: " + ", ".join(order)
                                   + ". Перевірте GEMINI_MODELS (скрипт scripts/check_api.py покаже доступні).")
        raise seen_errors[-1]

    checks = run_checks(copy, req)
    repaired = False
    hard = [c for c in checks if not c.ok and c.severity == "error"]
    if hard and not mock:   # одна спроба самовиправлення: показуємо моделі, що саме порушено
        try:
            copy2 = ask(used, build_prompt(req, feedback_from(checks)))
            checks2 = run_checks(copy2, req)
            if len([c for c in checks2 if not c.ok and c.severity == "error"]) <= len(hard):
                copy, checks, repaired = copy2, checks2, True
        except CopygenError:
            pass

    result = GenerationResult(
        copy=copy, checks=checks, model=used, attempts=counters["attempts"],
        latency_s=time.perf_counter() - t0, prompt_tokens=counters["p"], output_tokens=counters["o"],
        total_tokens=counters["t"], mock=mock, repaired=repaired)
    if not mock:
        _CACHE[cache_key] = result
        while len(_CACHE) > CACHE_MAX:
            _CACHE.popitem(last=False)
    return result
