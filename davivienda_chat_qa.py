import argparse
import os
import re
import time
import unicodedata
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import cloudscraper
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain_ollama import ChatOllama


load_dotenv()

PERSONAS_URL = os.getenv("TARGET_URL", "https://daviviendacorredorescolab.dvvapps.io")
BASE_URL = f"{urlparse(PERSONAS_URL).scheme}://{urlparse(PERSONAS_URL).netloc}"
ALLOWED_DOMAIN = urlparse(BASE_URL).netloc
PERSONAS_PATH_PREFIX = urlparse(PERSONAS_URL).path.rstrip("/") or "/"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

ANTI_BOT_MARKERS = ("pardon our interruption", "noindex, nofollow")

LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))

_NOT_FOUND_PHRASES = (
    "no encontre esa informacion",
    "no encontre",
    "no dispongo de informacion tecnica suficiente",
    "no dispongo de informacion",
    "no tengo informacion",
    "no cuento con informacion",
)

_NAV_FRAGMENTS = frozenset({
    "daviplata", "pse", "oficinas", "consultar todos los productos",
    "consultar todos", "ver mas", "descargar", "siguiente", "anterior",
    "ir al inicio", "click aqui", "haz clic", "contactenos",
    "redes sociales", "siguenos", "facebook", "twitter", "instagram",
    "linkedin", "terminos y condiciones", "politica de privacidad",
    "mapa del sitio", "preguntas frecuentes", "faq", "inicio sesion",
    "iniciar sesion", "registrate", "banca virtual", "menu",
    "inicio", "chat", "whatsapp", "cookie",
    "aceptar", "continuar", "suscribete",
})

_NOISE_CLASS_ID_FRAGMENTS = frozenset({
    "header", "footer", "nav", "menu", "navbar", "aside",
    "sidebar", "breadcrumb", "cookie", "legal", "social",
    "share", "popup", "modal", "banner", "chat", "whatsapp",
})

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

PERSONAS_SEED_URLS: List[str] = []


@dataclass
class Document:
    url: str
    title: str
    text: str


STOPWORDS_ES = {
    "de",
    "la",
    "el",
    "los",
    "las",
    "y",
    "o",
    "u",
    "en",
    "para",
    "por",
    "con",
    "sin",
    "que",
    "como",
    "cuál",
    "cual",
    "donde",
    "cuando",
    "es",
    "son",
    "un",
    "una",
    "unos",
    "unas",
    "al",
    "del",
    "se",
    "lo",
    "le",
    "les",
    "mi",
    "tu",
    "su",
    "sus",
    "me",
    "te",
    "nos",
    "si",
}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_match(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


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
    out = []
    for w in words:
        if w in STOPWORDS_ES or len(w) <= 2:
            continue
        out.append(normalize_term(w))
    return out


def _extract_urls(text: str) -> List[str]:
    urls = re.findall(r"https?://[^\s)]+", text)
    return list(dict.fromkeys(urls))


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_text = normalize_for_match(text)
    normalized_phrase = normalize_for_match(phrase)
    pattern = rf"\b{re.escape(normalized_phrase)}\b"
    return re.search(pattern, normalized_text) is not None


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


def _competitor_guardrail_response(question: str, docs: List[Document]) -> Optional[str]:
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


def is_allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc and not parsed.netloc.endswith(ALLOWED_DOMAIN):
        return False

    blocked_suffixes = (".pdf", ".zip", ".jpg", ".jpeg", ".png", ".gif", ".webp")
    if parsed.path.lower().endswith(blocked_suffixes):
        return False

    if "/download" in parsed.path.lower():
        return False

    return True


def is_personas_scope(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if PERSONAS_PATH_PREFIX == "/":
        return True
    return path.startswith(PERSONAS_PATH_PREFIX)


def fetch_url(session: requests.Session, url: str, timeout: int = 20) -> str:
    try:
        resp = session.get(url, timeout=timeout)
        if resp.status_code == 200 and not is_antibot_page(resp.text):
            return resp.text
    except requests.RequestException:
        pass

    # Fallback robusto: cloudscraper suele pasar filtros anti-bot donde requests falla.
    html = fetch_url_cloudscraper(url=url, timeout=timeout)
    if html and not is_antibot_page(html):
        return html

    # Fallback final: urllib.
    return fetch_url_urllib(url=url, timeout=timeout)


def is_antibot_page(html: str) -> bool:
    h = html.lower()
    return any(marker in h for marker in ANTI_BOT_MARKERS)


def fetch_url_urllib(url: str, timeout: int = 20) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = response.read()
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def fetch_url_cloudscraper(url: str, timeout: int = 20) -> str:
    try:
        scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
        response = scraper.get(url, timeout=timeout)
        if response.status_code != 200:
            return ""
        return response.text
    except Exception:
        return ""


def parse_sitemap_urls(session: requests.Session, sitemap_url: str) -> List[str]:
    xml = fetch_url(session, sitemap_url)
    if not xml:
        return []

    soup = BeautifulSoup(xml, "xml")
    urls = []

    for loc in soup.find_all("loc"):
        candidate = loc.get_text(strip=True)
        if candidate and is_allowed_url(candidate):
            urls.append(candidate)

    return urls


def _tag_has_noise_marker(tag) -> bool:
    tag_id = tag.get("id")
    classes = tag.get("class") or []

    parts = []
    if isinstance(tag_id, str):
        parts.append(tag_id.lower())

    for cls in classes:
        if isinstance(cls, str):
            parts.append(cls.lower())

    if not parts:
        return False

    joined = " ".join(parts)
    return any(fragment in joined for fragment in _NOISE_CLASS_ID_FRAGMENTS)


def _remove_layout_noise(soup: BeautifulSoup) -> None:
    for tag in soup([
        "script",
        "style",
        "noscript",
        "svg",
        "header",
        "footer",
        "nav",
        "aside",
        "form",
        "button",
        "iframe",
        "template",
    ]):
        tag.decompose()

    for noisy in soup.find_all(_tag_has_noise_marker):
        noisy.decompose()


def _is_boilerplate_text(text: str) -> bool:
    norm = normalize_for_match(text)
    if not norm:
        return True

    if any(frag in norm for frag in _NAV_FRAGMENTS):
        return True

    words = re.findall(r"\w+", norm)
    if len(words) < 4 and len(norm) < 40:
        return True

    if len(words) >= 25:
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.35:
            return True

    return False


def _is_link_heavy_text(text: str) -> bool:
    norm = normalize_for_match(text)
    words = re.findall(r"\w+", norm)
    if not words:
        return True

    url_hits = len(re.findall(r"https?://|www\.", norm))
    cta_hits = len(re.findall(r"\b(click|haz clic|aqui|aqui\.|descargar)\b", norm))

    if url_hits >= 2 and len(words) < 40:
        return True
    if cta_hits >= 2 and len(words) < 18:
        return True

    return False


def _split_text_units(text: str) -> List[str]:
    units = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [normalize_text(unit) for unit in units if normalize_text(unit)]


def _unit_signature(text: str) -> str:
    terms = tokenize(text)
    if terms:
        signature_terms = sorted(set(terms))[:12]
        return "|".join(signature_terms)
    return normalize_for_match(text)[:120]


def _deduplicate_units(units: List[str], max_units: int = 140) -> List[str]:
    out = []
    seen_exact = set()
    seen_signature = set()

    for unit in units:
        normalized = normalize_text(unit)
        if not normalized:
            continue
        if _is_boilerplate_text(normalized):
            continue
        if _is_link_heavy_text(normalized):
            continue

        exact_key = normalize_for_match(normalized)
        if exact_key in seen_exact:
            continue

        signature_key = _unit_signature(normalized)
        if signature_key in seen_signature:
            continue

        seen_exact.add(exact_key)
        seen_signature.add(signature_key)
        out.append(normalized)

        if len(out) >= max_units:
            break

    return out


def _finalize_clean_text(text: str) -> str:
    units = _split_text_units(text)
    cleaned_units = _deduplicate_units(units)
    return normalize_text(" ".join(cleaned_units))


def _collect_semantic_chunks(node) -> List[str]:
    chunks = []
    seen = set()

    for item in node.find_all(["h1", "h2", "h3", "p", "li"]):
        text = normalize_text(item.get_text(" ", strip=True))
        if not text:
            continue
        if _is_boilerplate_text(text):
            continue
        if _is_link_heavy_text(text):
            continue

        key = normalize_for_match(text)
        if key in seen:
            continue

        seen.add(key)
        chunks.append(text)

    return chunks


def _passes_content_quality_gate(text: str) -> bool:
    if len(text) < 220:
        return False

    units = _split_text_units(text)
    if not units:
        return False

    if len(units) < 3:
        return False

    noise_hits = sum(1 for part in units if _is_boilerplate_text(part))
    link_heavy_hits = sum(1 for part in units if _is_link_heavy_text(part))
    unique_ratio = len({normalize_for_match(part) for part in units}) / len(units)

    if (noise_hits / len(units)) >= 0.40:
        return False
    if (link_heavy_hits / len(units)) >= 0.30:
        return False
    if unique_ratio < 0.50:
        return False

    return True


def extract_page_text(html: str) -> Tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")

    title = soup.title.get_text(strip=True) if soup.title else "Sin titulo"
    _remove_layout_noise(soup)

    candidates = []
    for selector in ["main", "article", "section"]:
        nodes = soup.select(selector)
        for node in nodes:
            chunks = _collect_semantic_chunks(node)
            if not chunks:
                continue

            text = normalize_text(" ".join(chunks))
            if _passes_content_quality_gate(text):
                candidates.append(text)

    if not candidates:
        fallback_root = soup.body if soup.body else soup
        chunks = _collect_semantic_chunks(fallback_root)
        text = normalize_text(" ".join(chunks))
        if not _passes_content_quality_gate(text):
            text = normalize_text(soup.get_text(" ", strip=True))
    else:
        # Prioriza el bloque más grande de texto útil.
        text = max(candidates, key=len)

    text = _finalize_clean_text(text)

    return title, text


def extract_internal_links(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        absolute = urljoin(base_url, a["href"])
        if is_allowed_url(absolute):
            links.append(absolute)
    return links


def extract_personas_urls_from_raw(html: str) -> List[str]:
    urls = []

    domain_pattern = re.escape(BASE_URL)
    absolute = re.findall(rf"{domain_pattern}[^\"'\s)]+", html)
    for u in absolute:
        if is_personas_scope(u) and is_allowed_url(u):
            urls.append(u)

    path_pattern = re.escape(PERSONAS_PATH_PREFIX)
    relative = re.findall(rf"{path_pattern}[^\"'\s)]*", html)
    for u in relative:
        abs_u = urljoin(BASE_URL, u)
        if is_personas_scope(abs_u) and is_allowed_url(abs_u):
            urls.append(abs_u)

    return urls


def build_corpus(session: requests.Session, max_pages: int, delay_sec: float = 1.0) -> List[Document]:
    sitemap_urls = parse_sitemap_urls(session, SITEMAP_URL)

    urls = [PERSONAS_URL]
    for u in PERSONAS_SEED_URLS:
        if u not in urls:
            urls.append(u)

    for u in sitemap_urls:
        if is_personas_scope(u) and u not in urls:
            urls.append(u)

    # Fallback 1: si sitemap falla o trae pocas páginas, usar enlaces internos de la página base.
    if len(urls) < min(5, max_pages):
        personas_html = fetch_url(session, PERSONAS_URL)
        if personas_html:
            for u in extract_internal_links(personas_html, PERSONAS_URL):
                if is_personas_scope(u) and u not in urls:
                    urls.append(u)
                if len(urls) >= max_pages:
                    break

    # Fallback 2: extraer URLs del HTML crudo (incluye rutas embebidas en scripts).
    if len(urls) < max_pages:
        for base_candidate in [PERSONAS_URL] + PERSONAS_SEED_URLS[:4]:
            base_html = fetch_url(session, base_candidate)
            if not base_html:
                continue

            for u in extract_personas_urls_from_raw(base_html):
                if u not in urls:
                    urls.append(u)
                if len(urls) >= max_pages:
                    break
            if len(urls) >= max_pages:
                break

    # Backfill: incluye algunas páginas generales si el sitemap de personas es corto.
    for u in sitemap_urls:
        if len(urls) >= max_pages:
            break
        if u not in urls:
            urls.append(u)

    urls = urls[:max_pages]

    docs: List[Document] = []
    for idx, url in enumerate(urls, start=1):
        try:
            html = fetch_url(session, url)
            if not html:
                continue

            if is_antibot_page(html):
                continue

            title, text = extract_page_text(html)
            if len(text) < 200 or not _passes_content_quality_gate(text):
                continue

            docs.append(Document(url=url, title=title, text=text))
            print(f"[{idx}/{len(urls)}] OK {url}")
            time.sleep(delay_sec)
        except requests.RequestException:
            continue

    return docs


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

        # Coincidencia flexible para variaciones como inversion/inversiones.
        prefix = t[:5]
        fuzzy_hits = 0
        for dt in doc_terms:
            if dt.startswith(prefix) or t.startswith(dt[:5]):
                fuzzy_hits += 1
        score += min(2.0, fuzzy_hits * 0.2)

    # Bonus por coincidencia exacta de frase corta.
    q_norm = normalize_text(question.lower())
    if len(q_norm) > 8 and q_norm in text_l:
        score += 6.0

    return score


def retrieve_top_docs(question: str, docs: List[Document], top_k: int) -> List[Document]:
    ranked = sorted(docs, key=lambda d: score_doc(question, d), reverse=True)
    top = [d for d in ranked[:top_k] if score_doc(question, d) > 0]
    if not top:
        # Fallback para no devolver vacío cuando hay poco contenido indexado.
        top = ranked[:top_k]
    return top


def build_prompt(question: str, docs: List[Document]) -> str:
    def compact_context_snippet(text: str, max_chars: int = 1800) -> str:
        units = _deduplicate_units(_split_text_units(text), max_units=22)
        if not units:
            return text[:max_chars]

        compact = normalize_text(" ".join(units))
        return compact[:max_chars]

    context_blocks = []
    for i, d in enumerate(docs, start=1):
        snippet = compact_context_snippet(d.text)
        context_blocks.append(
            f"FUENTE {i}\nURL: {d.url}\nTITULO: {d.title}\nCONTENIDO: {snippet}"
        )

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


def is_not_found_answer(answer: str) -> bool:
    normalized = normalize_for_match(answer)
    return any(phrase in normalized for phrase in _NOT_FOUND_PHRASES)


def _is_nav_sentence(sentence: str) -> bool:
    norm = normalize_for_match(sentence)
    if any(frag in norm for frag in _NAV_FRAGMENTS):
        return True
    if len(re.findall(r"\w+", norm)) < 7:
        return True
    return False


def _deduplicate_sources_section(text: str) -> str:
    urls = _extract_urls(text)
    parts = re.split(r"(?i)\*{0,2}\s*fuentes\s*\*{0,2}\s*\n", text, maxsplit=1)
    if len(parts) <= 1:
        return text

    body = parts[0].rstrip()
    if not urls:
        return body

    sources_block = "\n".join([f"* {u}" for u in urls])
    return f"{body}\n\n**Fuentes**\n{sources_block}"


def split_sentences(text: str) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", normalize_text(text))
    return [s for s in sentences if len(s) > 35]


def build_extractive_fallback(question: str, docs: List[Document], max_sentences: int = 4) -> str:
    q_terms = set(tokenize(question))
    candidates = []

    for doc in docs:
        for sentence in split_sentences(doc.text[:6000]):
            if _is_nav_sentence(sentence):
                continue
            if _is_boilerplate_text(sentence):
                continue
            if len(sentence) > 280:
                continue
            sent_terms = set(tokenize(sentence))
            overlap = len(q_terms.intersection(sent_terms))
            if overlap <= 0:
                continue
            score = overlap + (1 if "inversion" in normalize_for_match(sentence) else 0)
            candidates.append((score, sentence, doc.url))

    candidates.sort(key=lambda x: x[0], reverse=True)
    selected = []
    seen: set = set()
    selected_urls = []

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

    bullet_block = "\n".join([f"- {s}" for s in selected])
    sources_block = "\n".join([f"* {url}" for url in selected_urls])

    return (
        "Con base en el contenido publico de Davivienda Corredores, esto es lo mas relevante:\n"
        f"{bullet_block}\n\n"
        "**Fuentes**\n"
        f"{sources_block}"
    )


def answer_question(question: str, docs: List[Document], model: str, top_k: int) -> str:
    relevant = retrieve_top_docs(question, docs, top_k=top_k)
    if not relevant:
        return "No encontre esa informacion en el sitio analizado."

    competitor_block = _competitor_guardrail_response(question=question, docs=relevant)
    if competitor_block:
        return competitor_block

    prompt = build_prompt(question, relevant)
    llm = ChatOllama(model=model, temperature=LLM_TEMPERATURE)
    result = llm.invoke(prompt)
    answer = result.content if hasattr(result, "content") else str(result)
    answer = _deduplicate_sources_section(answer)

    if is_not_found_answer(answer):
        return build_extractive_fallback(question=question, docs=relevant)

    return answer


def run_single_question(question: str, max_pages: int, top_k: int, model: str) -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    docs = build_corpus(session=session, max_pages=max_pages)
    if not docs:
        print("No se pudo construir corpus de paginas publicas.")
        return

    print(f"\nPaginas indexadas: {len(docs)}")
    print("\n=== RESPUESTA ===")
    print(answer_question(question=question, docs=docs, model=model, top_k=top_k))


def run_chat(max_pages: int, top_k: int, model: str) -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    print("Construyendo indice inicial del sitio...\n")
    docs = build_corpus(session=session, max_pages=max_pages)
    if not docs:
        print("No se pudo construir corpus de paginas publicas.")
        return

    print(f"\nIndice listo con {len(docs)} paginas.")
    print("Escribe tu pregunta (o 'salir').\n")

    while True:
        question = input("Cliente> ").strip()
        if not question:
            continue
        if question.lower() in {"salir", "exit", "quit"}:
            break

        response = answer_question(question=question, docs=docs, model=model, top_k=top_k)
        print("\nAsistente>")
        print(response)
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Q&A con scraping para Davivienda Corredores usando Gemma local"
    )
    parser.add_argument("--question", type=str, default="", help="Pregunta unica")
    parser.add_argument("--max-pages", type=int, default=20, help="Maximo de paginas a indexar")
    parser.add_argument("--top-k", type=int, default=4, help="Cantidad de paginas relevantes por respuesta")
    parser.add_argument("--model", type=str, default=os.getenv("LOCAL_MODEL", "gemma4-financiero"), help="Modelo local de Ollama")

    args = parser.parse_args()

    if args.question:
        run_single_question(
            question=args.question,
            max_pages=args.max_pages,
            top_k=args.top_k,
            model=args.model,
        )
    else:
        run_chat(max_pages=args.max_pages, top_k=args.top_k, model=args.model)


if __name__ == "__main__":
    main()
