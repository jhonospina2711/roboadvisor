import re
from typing import List

from core.document import Document
from core.utils import normalize_for_match

STOPWORDS_ES = {
    "de", "la", "el", "los", "las", "y", "o", "u", "en", "para", "por",
    "con", "sin", "que", "como", "cuál", "cual", "donde", "cuando", "es",
    "son", "un", "una", "unos", "unas", "al", "del", "se", "lo", "le",
    "les", "mi", "tu", "su", "sus", "me", "te", "nos", "si",
}


def normalize_term(term: str) -> str:
    t = normalize_for_match(term)
    if t.endswith("es") and len(t) > 4:
        t = t[:-2]
    elif t.endswith("s") and len(t) > 3:
        t = t[:-1]
    return t


def tokenize(text: str) -> List[str]:
    normalized = normalize_for_match(text)
    words = re.findall(r"[a-zA-Z0-9]+", normalized)
    return [
        normalize_term(w)
        for w in words
        if w not in STOPWORDS_ES and len(w) > 2
    ]


def score_doc(question: str, doc: Document) -> float:
    q_terms = tokenize(question)
    if not q_terms:
        return 0.0

    text_l = normalize_for_match(doc.text)
    title_l = normalize_for_match(doc.title)
    doc_terms = set(tokenize(f"{doc.title} {doc.text[:12000]}"))

    score = 0.0
    for t in q_terms:
        if t in title_l:
            score += 3.0
        score += text_l.count(t) * 1.0

        prefix = t[:5]
        fuzzy_hits = sum(
            1 for dt in doc_terms
            if dt.startswith(prefix) or t.startswith(dt[:5])
        )
        score += min(2.0, fuzzy_hits * 0.2)

    q_norm = normalize_for_match(question)
    if len(q_norm) > 8 and q_norm in text_l:
        score += 6.0

    return score


def retrieve_top_docs(question: str, docs: List[Document], top_k: int) -> List[Document]:
    ranked = sorted(docs, key=lambda d: score_doc(question, d), reverse=True)
    top = [d for d in ranked[:top_k] if score_doc(question, d) > 0]
    return top if top else ranked[:top_k]
