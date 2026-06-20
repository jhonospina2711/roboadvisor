import re
from typing import List

from core.document import Document
from core.retrieval.search import tokenize
from core.utils import normalize_for_match

_NAV_FRAGMENTS = frozenset({
    "daviplata", "pse", "oficinas", "consultar todos", "ver mas",
    "descargar", "siguiente", "anterior", "ir al inicio", "click aqui",
    "haz clic", "contactenos", "redes sociales", "siguenos", "facebook",
    "twitter", "instagram", "linkedin", "terminos y condiciones",
    "politica de privacidad", "mapa del sitio", "preguntas frecuentes",
    "faq", "inicio sesion", "iniciar sesion", "registrate", "banca virtual",
    "menu", "inicio", "chat", "whatsapp", "cookie", "aceptar", "continuar",
})


def _is_nav_sentence(sentence: str) -> bool:
    norm = normalize_for_match(sentence)
    if any(frag in norm for frag in _NAV_FRAGMENTS):
        return True
    return len(re.findall(r"\w+", norm)) < 7


def _is_boilerplate(text: str) -> bool:
    norm = normalize_for_match(text)
    return not norm or any(frag in norm for frag in _NAV_FRAGMENTS)


def split_sentences(text: str) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text).strip())
    return [s for s in sentences if len(s) > 35]


def build_extractive_fallback(
    question: str,
    docs: List[Document],
    max_sentences: int = 4,
) -> str:
    q_terms = set(tokenize(question))
    candidates = []

    for doc in docs:
        for sentence in split_sentences(doc.text[:6000]):
            if _is_nav_sentence(sentence) or _is_boilerplate(sentence):
                continue
            if len(sentence) > 280:
                continue
            sent_terms = set(tokenize(sentence))
            overlap = len(q_terms.intersection(sent_terms))
            if overlap <= 0:
                continue
            bonus = 1 if "inversion" in normalize_for_match(sentence) else 0
            candidates.append((overlap + bonus, sentence, doc.url))

    candidates.sort(key=lambda x: x[0], reverse=True)

    selected: List[str] = []
    selected_urls: List[str] = []
    seen: set = set()

    for _, sentence, source_url in candidates:
        key = normalize_for_match(sentence)[:80]
        if any(key[:50] in s for s in seen):
            continue
        seen.add(key)
        selected.append(sentence)
        if source_url not in selected_urls:
            selected_urls.append(source_url)
        if len(selected) >= max_sentences:
            break

    if not selected:
        return "No encontre esa informacion en el sitio analizado."

    bullet_block = "\n".join(f"- {s}" for s in selected)
    sources_block = "\n".join(f"* {url}" for url in selected_urls)
    return (
        "Con base en el contenido publico de Davivienda Corredores, esto es lo mas relevante:\n"
        f"{bullet_block}\n\n**Fuentes**\n{sources_block}"
    )
