from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    def invoke(self, prompt: str) -> str:
        ...
