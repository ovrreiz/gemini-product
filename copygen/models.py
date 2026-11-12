"""Вхідний запит і результат (звичайні dataclass без зовнішніх залежностей)."""
import hashlib
import json
import re
from dataclasses import dataclass, field, asdict

from .config import PLATFORMS, LANGUAGES, TONES
from .errors import InvalidRequest

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(s: str) -> str:
    """Прибирає керівні символи й зайві пробіли по краях."""
    return _CONTROL.sub("", s or "").strip()


@dataclass(frozen=True)
class ProductRequest:
    name: str
    features: tuple          # рядки з характеристиками
    audience: str = ""
    platform: str = "marketplace"
    language: str = "uk"
    tone: str = "Дружній"
    emoji: bool = False

    @staticmethod
    def from_form(name, features_text, audience, platform, language, tone, emoji) -> "ProductRequest":
        feats = tuple(clean_text(x) for x in (features_text or "").splitlines() if clean_text(x))
        return ProductRequest(clean_text(name), feats, clean_text(audience), platform, language, tone, bool(emoji))

    def validate(self) -> None:
        if not (2 <= len(self.name) <= 120):
            raise InvalidRequest("Назва товару має містити від 2 до 120 символів.")
        if not (1 <= len(self.features) <= 15):
            raise InvalidRequest("Вкажіть від 1 до 15 характеристик (кожна з нового рядка).")
        if any(len(f) > 200 for f in self.features):
            raise InvalidRequest("Кожна характеристика має бути не довшою за 200 символів.")
        if len(self.audience) > 200:
            raise InvalidRequest("Опис аудиторії має бути не довшим за 200 символів.")
        if self.platform not in PLATFORMS:
            raise InvalidRequest("Невідома платформа.")
        if self.language not in LANGUAGES:
            raise InvalidRequest("Невідома мова.")
        if self.tone not in TONES:
            raise InvalidRequest("Невідомий тон.")

    def input_text(self) -> str:
        """Увесь текст, який ввів користувач (для перевірки «чи не вигадані числа»)."""
        return " ".join([self.name, *self.features, self.audience])

    def to_dict(self) -> dict:
        d = asdict(self)
        d["features"] = list(self.features)
        return d

    def cache_key(self, model: str, temperature: float) -> str:
        blob = json.dumps([self.to_dict(), model, round(temperature, 2)], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class ProductCopy:
    title: str
    short_description: str
    long_description: str
    hashtags: list
    call_to_action: str
    keywords: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Check:
    name: str
    ok: bool
    severity: str   # "error" — порушено жорстку вимогу, "warn" — лише попередження
    detail: str


@dataclass
class GenerationResult:
    copy: ProductCopy
    checks: list
    model: str
    attempts: int
    latency_s: float
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    mock: bool = False
    from_cache: bool = False
    repaired: bool = False

    @property
    def hard_errors(self) -> list:
        return [c for c in self.checks if not c.ok and c.severity == "error"]
