import os

from core.llm.base import LLMClient

_OLLAMA_DEFAULT = "gemma4-financiero"
_GEMINI_DEFAULT = "gemini-2.0-flash"


def get_default_model() -> str:
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    if provider == "gemini":
        return os.getenv("GEMINI_MODEL", _GEMINI_DEFAULT)
    return os.getenv("LOCAL_MODEL", _OLLAMA_DEFAULT)


def get_llm_client(model: str | None = None, temperature: float | None = None) -> LLMClient:
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    resolved_model = model or get_default_model()
    resolved_temp = temperature if temperature is not None else float(os.getenv("LLM_TEMPERATURE", "0"))

    if provider == "ollama":
        from core.llm.ollama.client import OllamaClient
        return OllamaClient(model=resolved_model, temperature=resolved_temp)

    if provider == "gemini":
        from core.llm.gemini.client import GeminiClient
        return GeminiClient(model=resolved_model, temperature=resolved_temp)

    raise ValueError(
        f"LLM_PROVIDER='{provider}' no reconocido. "
        "Valores válidos: 'ollama', 'gemini'."
    )
