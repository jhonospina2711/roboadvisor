import os
import ssl

from langchain_google_genai import ChatGoogleGenerativeAI


def _no_verify_ssl_context() -> ssl.SSLContext:
    """Create an SSL context that skips certificate verification.

    google-genai checks ``if not client_args.get("verify")`` and replaces a
    bare ``False`` with the system CA bundle.  Passing a truthy SSLContext
    object that has verification disabled bypasses that override.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class GeminiClient:
    def __init__(self, model: str, temperature: float = 0.0) -> None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GOOGLE_API_KEY no está configurado. "
                "Agrega la variable al archivo .env para usar Gemini."
            )
        # client_args is forwarded as **kwargs to httpx.Client inside google-genai.
        # We pass a disabled SSLContext (truthy) so the SDK does not override it.
        client_args = (
            {"verify": _no_verify_ssl_context()}
            if os.getenv("GEMINI_SSL_VERIFY", "true").lower() == "false"
            else {}
        )
        self._llm = ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            google_api_key=api_key,
            client_args=client_args,
        )

    def invoke(self, prompt: str) -> str:
        result = self._llm.invoke(prompt)
        content = result.content if hasattr(result, "content") else str(result)
        if isinstance(content, list):
            # Thinking-enabled models return a list of parts (thinking + text).
            # Extract only the text parts, skip thinking blocks.
            parts = [
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in content
                if not (isinstance(p, dict) and p.get("type") == "thinking")
            ]
            return "\n".join(p for p in parts if p).strip()
        return content



