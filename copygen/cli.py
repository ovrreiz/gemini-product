"""Командний рядок: швидка перевірка без веб-інтерфейсу.

Приклад:
  python -m copygen.cli --name "Термокружка Nord" --feature "Об'єм 450 мл" --feature "Тримає тепло 8 годин" \
      --platform instagram --language uk --tone Дружній            # реальний Gemini (потрібен GEMINI_API_KEY)
  python -m copygen.cli --name "Термокружка Nord" --feature "Об'єм 450 мл" --mock  # демо без ключа
"""
import argparse
import dataclasses
import json
import sys

from .config import PLATFORMS, LANGUAGES, TONES, settings_from_env
from .errors import CopygenError
from .llm import generate
from .models import ProductRequest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Генератор описів товарів (Gemini API)")
    ap.add_argument("--name", required=True)
    ap.add_argument("--feature", action="append", required=True, help="характеристика (можна кілька разів)")
    ap.add_argument("--audience", default="")
    ap.add_argument("--platform", default="marketplace", choices=list(PLATFORMS))
    ap.add_argument("--language", default="uk", choices=list(LANGUAGES))
    ap.add_argument("--tone", default="Дружній", choices=list(TONES))
    ap.add_argument("--emoji", action="store_true")
    ap.add_argument("--model", default=None)
    ap.add_argument("--mock", action="store_true", help="демо-режим без звернення до API")
    a = ap.parse_args(argv)

    settings = settings_from_env()
    if a.mock:
        settings = dataclasses.replace(settings, mock=True)
    req = ProductRequest.from_form(a.name, "\n".join(a.feature), a.audience, a.platform, a.language, a.tone, a.emoji)
    try:
        res = generate(req, settings, model=a.model)
    except CopygenError as e:
        print(f"Помилка: {e}", file=sys.stderr)
        return 1
    print(json.dumps(res.copy.to_dict(), ensure_ascii=False, indent=2))
    print(f"\nМодель: {res.model} | спроб: {res.attempts} | {res.latency_s:.2f} с | "
          f"токени: {res.prompt_tokens}+{res.output_tokens} | виправлено: {res.repaired}", file=sys.stderr)
    for c in res.checks:
        print(f"  [{'OK' if c.ok else ('ПОМИЛКА' if c.severity == 'error' else 'УВАГА')}] {c.name}: {c.detail}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
