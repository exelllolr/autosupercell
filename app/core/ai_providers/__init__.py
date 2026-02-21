"""AI провайдеры для поиска товаров."""

from app.core.ai_providers.base import BaseAIProvider
from app.core.ai_providers.openai_provider import OpenAIProvider

# Claude/Gemini зависимости могут быть не установлены в минимальной среде.
try:
    from app.core.ai_providers.claude_provider import ClaudeProvider  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    ClaudeProvider = None  # type: ignore

try:
    from app.core.ai_providers.gemini_provider import GeminiProvider  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    GeminiProvider = None  # type: ignore

__all__ = [
    "BaseAIProvider",
    "OpenAIProvider",
    "ClaudeProvider",
    "GeminiProvider",
]
