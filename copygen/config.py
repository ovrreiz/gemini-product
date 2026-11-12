"""Налаштування: платформи, мови, тони, змінні середовища.

Ліміти довжини для платформ — ДЕМОНСТРАЦІЙНІ цільові значення застосунку (щоб було що перевіряти),
а не офіційні вимоги майданчиків. Їх можна змінити тут.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformSpec:
    key: str
    label: str
    title_max: int
    short_max: int
    long_max: int
    tags_min: int
    tags_max: int
    style_hint: str


PLATFORMS = {
    "marketplace": PlatformSpec(
        "marketplace", "Маркетплейс (OLX, Prom, Rozetka)", 70, 160, 1000, 3, 5,
        "Factual, scannable listing text: key specs first, no hype, no exaggerated claims."),
    "instagram": PlatformSpec(
        "instagram", "Instagram", 60, 125, 1200, 5, 12,
        "Engaging caption: a strong first line (hook), short paragraphs, a clear call to action."),
    "telegram": PlatformSpec(
        "telegram", "Telegram-канал", 80, 200, 1000, 2, 5,
        "Concise channel post: one idea, a clear benefit, a direct call to action."),
    "linkedin": PlatformSpec(
        "linkedin", "LinkedIn", 100, 200, 1300, 3, 5,
        "Professional tone: value for the customer or business, evidence from the given facts only."),
}

# ключ -> (назва для інтерфейсу, назва англійською для промпта)
LANGUAGES = {
    "uk": ("Українська", "Ukrainian"),
    "en": ("English", "English"),
    "pl": ("Polski", "Polish"),
    "de": ("Deutsch", "German"),
}

TONES = {
    "Діловий": "professional and neutral",
    "Дружній": "warm, friendly and conversational",
    "Жартівливий": "light, witty and playful (but not offensive)",
    "Преміум": "elegant, refined, understated luxury",
    "Емоційний": "emotional, inspiring, enthusiastic",
}

# Модель за замовчуванням і запасні: назви моделей Gemini змінюються й закриваються,
# тому список налаштовується змінною GEMINI_MODELS (через кому). Перший елемент — основна модель.
DEFAULT_MODELS = ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.5-flash")


@dataclass(frozen=True)
class Settings:
    api_key: str = ""
    models: tuple = DEFAULT_MODELS
    mock: bool = True
    timeout_s: int = 30
    max_retries: int = 2
    max_tokens: int = 4096
    max_requests_per_session: int = 20
    app_password: str = ""

    @property
    def has_key(self) -> bool:
        return bool(self.api_key.strip())


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def settings_from_env() -> Settings:
    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    raw_models = os.environ.get("GEMINI_MODELS", "")
    models = tuple(m.strip() for m in raw_models.split(",") if m.strip()) or DEFAULT_MODELS
    mock_env = os.environ.get("MOCK", "").strip().lower()
    mock = mock_env in ("1", "true", "yes") if mock_env else not key
    return Settings(
        api_key=key,
        models=models,
        mock=mock,
        timeout_s=_int_env("REQUEST_TIMEOUT_S", 30),
        max_requests_per_session=_int_env("MAX_REQUESTS_PER_SESSION", 20),
        app_password=os.environ.get("APP_PASSWORD", ""),
    )
