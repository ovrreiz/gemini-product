"""Автоматична перевірка якості відповіді (довжина, хештеги, мова, вигадані числа)."""
import re

from .config import PLATFORMS
from .models import Check, ProductCopy, ProductRequest

_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers(text: str) -> set:
    return {n.replace(",", ".") for n in _NUM.findall(text)}


def _letters_ratio(text: str, cyrillic: bool) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 1.0
    cyr = sum(1 for c in letters if "\u0400" <= c <= "\u04ff")
    return cyr / len(letters) if cyrillic else (len(letters) - cyr) / len(letters)


def run_checks(copy: ProductCopy, req: ProductRequest) -> list:
    spec = PLATFORMS[req.platform]
    res = []

    def limit(name, text, mx):
        ok = len(text) <= mx
        res.append(Check(name, ok, "error", f"{len(text)} з {mx} символів"))

    limit("Довжина заголовка", copy.title, spec.title_max)
    limit("Довжина короткого опису", copy.short_description, spec.short_max)
    limit("Довжина повного опису", copy.long_description, spec.long_max)

    n = len(copy.hashtags)
    res.append(Check("Кількість хештегів", spec.tags_min <= n <= spec.tags_max, "error",
                     f"{n} (потрібно {spec.tags_min}–{spec.tags_max})"))
    res.append(Check("Заклик до дії", bool(copy.call_to_action.strip()), "error",
                     "є" if copy.call_to_action.strip() else "відсутній"))

    # Вигадані числа: цифри у відповіді, яких не було у вхідних даних (евристика)
    allowed = _numbers(req.input_text())
    body = " ".join([copy.title, copy.short_description, copy.long_description, copy.call_to_action])
    extra = sorted(_numbers(body) - allowed)
    res.append(Check("Відсутність вигаданих чисел", not extra, "warn",
                     "усі числа є у ваших даних" if not extra else "нових чисел немає у вхідних даних: " + ", ".join(extra[:6])))

    # Мова: українська — переважно кирилиця, інші — переважно латиниця
    sample = " ".join([copy.short_description, copy.long_description])
    ratio = _letters_ratio(sample, cyrillic=(req.language == "uk"))
    need = 0.5 if req.language == "uk" else 0.8
    res.append(Check("Відповідність мові", ratio >= need, "warn", f"{ratio:.0%} літер очікуваного письма"))
    return res


def feedback_from(checks: list) -> list:
    """Список вимог, які порушено, — для повторного запиту до моделі."""
    return [f"{c.name}: {c.detail}" for c in checks if not c.ok and c.severity == "error"]
