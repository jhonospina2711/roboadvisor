import re
from typing import Dict, List, Optional, Tuple

from core.document import Document
from core.utils import normalize_for_match

_COMPETITOR_ALIASES: Dict[str, Tuple[str, ...]] = {
    "Bancolombia": ("bancolombia",),
    "BBVA": ("bbva", "bbva colombia"),
    "Skandia": ("skandia", "old mutual"),
    "Itaú": ("itau", "itaú"),
    "Scotiabank Colpatria": ("scotiabank", "colpatria", "scotiabank colpatria"),
    "Banco de Bogota": ("banco de bogota", "banco de bogotá"),
    "Banco de Occidente": ("banco de occidente",),
    "Banco Popular": ("banco popular",),
    "Banco AV Villas": ("av villas", "avvillas", "banco av villas"),
    "Fiduciaria Sura": ("sura", "fiduciaria sura"),
}


def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = rf"\b{re.escape(normalize_for_match(phrase))}\b"
    return re.search(pattern, normalize_for_match(text)) is not None


def _detect_competitor_entity(question: str) -> Optional[str]:
    for entity, aliases in _COMPETITOR_ALIASES.items():
        for alias in aliases:
            if _contains_phrase(question, alias):
                return entity
    return None


def _docs_contain_entity(docs: List[Document], aliases: Tuple[str, ...]) -> bool:
    for doc in docs:
        combined = f"{doc.title} {doc.text[:8000]}"
        for alias in aliases:
            if _contains_phrase(combined, alias):
                return True
    return False


def check_competitor_guardrail(question: str, docs: List[Document]) -> Optional[str]:
    """Returns a canned refusal string if the question asks about a competitor
    that is not present in the retrieved docs. Returns None otherwise."""
    entity = _detect_competitor_entity(question)
    if not entity:
        return None
    aliases = _COMPETITOR_ALIASES[entity]
    if _docs_contain_entity(docs, aliases):
        return None
    return (
        f"No dispongo de informacion tecnica sobre {entity} en mi base de datos local. "
        "Solo puedo asesorarte sobre los productos y beneficios de Davivienda Corredores."
    )
