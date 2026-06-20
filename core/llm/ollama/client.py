from langchain_ollama import ChatOllama


class OllamaClient:
    def __init__(self, model: str, temperature: float = 0.0) -> None:
        self._llm = ChatOllama(model=model, temperature=temperature)

    def invoke(self, prompt: str) -> str:
        result = self._llm.invoke(prompt)
        return result.content if hasattr(result, "content") else str(result)
