import re
from typing import List

from core.document import Document
from core.llm.base import LLMClient
from core.qa.fallback import build_extractive_fallback
from core.qa.guardrails import check_competitor_guardrail
from core.retrieval.search import retrieve_top_docs
from core.scraping.parser import _deduplicate_units, _split_text_units
from core.utils import normalize_for_match, normalize_text

_NOT_FOUND_PHRASES = (
    "no encontre esa informacion",
    "no encontre",
    "no dispongo de informacion tecnica suficiente",
    "no dispongo de informacion",
    "no tengo informacion",
    "no cuento con informacion",
)


def build_prompt(question: str, docs: List[Document]) -> str:
    def compact_snippet(text: str, max_chars: int = 1800) -> str:
        units = _deduplicate_units(_split_text_units(text), max_units=22)
        compact = normalize_text(" ".join(units)) if units else text
        return compact[:max_chars]

    context_blocks = [
        f"FUENTE {i}\nURL: {d.url}\nTITULO: {d.title}\nCONTENIDO: {compact_snippet(d.text)}"
        for i, d in enumerate(docs, start=1)
    ]
    context = "\n\n".join(context_blocks)

    return f"""
Eres un asistente para clientes de Davivienda Corredores.
Responde SIEMPRE en espanol claro.
Usa SOLO la informacion del CONTEXTO.
Si la respuesta no esta en el contexto, di: "No encontre esa informacion en el sitio analizado".
No inventes datos.
Al final agrega una seccion llamada "Fuentes" con las URLs usadas.

PREGUNTA DEL CLIENTE:
{question}

CONTEXTO:
{context}
""".strip()


def _is_not_found_answer(answer: str) -> bool:
    normalized = normalize_for_match(answer)
    return any(phrase in normalized for phrase in _NOT_FOUND_PHRASES)


def _deduplicate_sources_section(text: str) -> str:
    urls = re.findall(r"https?://[^\s)]+", text)
    parts = re.split(r"(?i)\*{0,2}\s*fuentes\s*\*{0,2}\s*\n", text, maxsplit=1)
    if len(parts) <= 1:
        return text
    body = parts[0].rstrip()
    if not urls:
        return body
    sources_block = "\n".join(f"* {u}" for u in dict.fromkeys(urls))
    return f"{body}\n\n**Fuentes**\n{sources_block}"


def answer_question(
    question: str,
    docs: List[Document],
    llm: LLMClient,
    top_k: int,
) -> str:
    relevant = retrieve_top_docs(question, docs, top_k=top_k)
    if not relevant:
        return "No encontre esa informacion en el sitio analizado."

    guardrail = check_competitor_guardrail(question=question, docs=relevant)
    if guardrail:
        return guardrail

    prompt = build_prompt(question, relevant)
    answer = llm.invoke(prompt)
    answer = _deduplicate_sources_section(answer)

    if _is_not_found_answer(answer):
        return build_extractive_fallback(question=question, docs=relevant)

    return answer
