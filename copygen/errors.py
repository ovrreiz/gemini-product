"""Винятки застосунку. Усі успадковуються від CopygenError, тому UI ловить їх одним except."""


class CopygenError(Exception):
    """Базовий виняток; текст повідомлення можна показувати користувачу."""


class InvalidRequest(CopygenError):
    """Некоректні вхідні дані форми."""


class ApiKeyMissing(CopygenError):
    """Не задано API-ключ Gemini."""


class ApiKeyInvalid(CopygenError):
    """Ключ відхилено сервером (невірний, відкликаний або без дозволу)."""


class QuotaExceeded(CopygenError):
    """Вичерпано ліміт запитів (HTTP 429) для всіх моделей зі списку."""


class ModelUnavailable(CopygenError):
    """Жодна модель зі списку недоступна (не знайдена / закрита)."""


class EmptyResponse(CopygenError):
    """Модель повернула порожню відповідь (блокування, ліміт токенів)."""


class BadResponse(CopygenError):
    """Відповідь не є коректним JSON або не відповідає схемі."""


class ServiceUnavailable(CopygenError):
    """Сервіс тимчасово недоступний після всіх повторних спроб."""


class BackendError(Exception):
    """Помилка нижнього рівня (HTTP-код, статус, текст). Створюється бекендами, не показується напряму."""

    def __init__(self, code: int, message: str, status: str = ""):
        super().__init__(f"{code} {status}: {message}")
        self.code = code
        self.message = message
        self.status = status
