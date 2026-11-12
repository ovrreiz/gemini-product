"""Перевірка ключа й моделей: показує, які моделі Gemini доступні вашому ключу, і робить один тестовий запит.

Запуск:  export GEMINI_API_KEY="..."  &&  python scripts/check_api.py [назва_моделі]
Якщо модель із GEMINI_MODELS закрили чи перейменували — оберіть актуальну з виводу й задайте її в GEMINI_MODELS.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from copygen.config import settings_from_env  # noqa: E402
from copygen.llm import GeminiBackend  # noqa: E402
from copygen.errors import BackendError  # noqa: E402


def main() -> int:
    s = settings_from_env()
    if not s.has_key:
        print("Задайте GEMINI_API_KEY (export GEMINI_API_KEY=...).")
        return 1
    try:
        from google import genai
    except ImportError:
        print("Встановіть залежності: pip install -r requirements.txt")
        return 1

    client = genai.Client(api_key=s.api_key)
    print("Моделі, доступні вашому ключу (з generateContent):")
    names = []
    try:
        for m in client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            name = (m.name or "").replace("models/", "")
            if "gemini" in name and (not actions or "generateContent" in actions):
                names.append(name)
    except Exception as e:
        print(f"Не вдалося отримати список моделей: {e}")
    for n in sorted(names):
        print("  ", n)

    model = sys.argv[1] if len(sys.argv) > 1 else s.models[0]
    print(f"\nТестовий запит до моделі «{model}»…")
    try:
        r = GeminiBackend(s.api_key, s.timeout_s).generate_json(
            model, "Reply with a short JSON.", 'Return {"ok": true} as JSON.', 0.0, 256)
        print("Відповідь:", (r.text or "<порожньо>")[:200], "| токени:", r.total_tokens)
        return 0
    except BackendError as e:
        print(f"Помилка {e.code} {e.status}: {e.message[:300]}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
