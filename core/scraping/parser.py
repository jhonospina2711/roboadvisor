import re
from typing import List, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core.utils import normalize_for_match, normalize_text

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
    "footer", "nav", "menu", "navbar", "aside",
    "sidebar", "breadcrumb", "cookie", "legal",
    "share", "popup", "modal", "banner", "chat", "whatsapp",
})

_LAYOUT_TAGS = [
    "script", "style", "noscript", "svg", "footer",
    "nav", "aside", "form", "button", "iframe", "template",
]


def extract_page_text(html: str) -> Tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else "Sin titulo"
    _remove_layout_noise(soup)

    candidates = []
    for selector in ["main", "article", "section"]:
        for node in soup.select(selector):
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
        text = max(candidates, key=len)

    text = _finalize_clean_text(text)
    return title, text


def extract_internal_links(html: str, base_url: str) -> List[str]:
    from core.scraping.corpus import is_allowed_url

    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        absolute = urljoin(base_url, a["href"])
        if is_allowed_url(absolute):
            links.append(absolute)
    return links


def extract_personas_urls_from_raw(html: str, base_url: str, path_prefix: str) -> List[str]:
    from core.scraping.corpus import is_allowed_url, is_personas_scope

    urls = []
    domain_pattern = re.escape(base_url)
    for u in re.findall(rf"{domain_pattern}[^\"'\s)]+", html):
        if is_personas_scope(u) and is_allowed_url(u):
            urls.append(u)

    path_pattern = re.escape(path_prefix)
    for u in re.findall(rf"{path_pattern}[^\"'\s)]*", html):
        abs_u = urljoin(base_url, u)
        if is_personas_scope(abs_u) and is_allowed_url(abs_u):
            urls.append(abs_u)

    return urls


# --- private helpers ---

def _remove_layout_noise(soup: BeautifulSoup) -> None:
    for tag in soup(_LAYOUT_TAGS):
        tag.decompose()
    for noisy in soup.find_all(_tag_has_noise_marker):
        noisy.decompose()


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


def _is_boilerplate_text(text: str) -> bool:
    norm = normalize_for_match(text)
    if not norm:
        return True
    if any(frag in norm for frag in _NAV_FRAGMENTS):
        return True
    words = re.findall(r"\w+", norm)
    if len(words) < 4 and len(norm) < 40:
        return True
    if len(words) >= 25 and len(set(words)) / len(words) < 0.35:
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


def _collect_semantic_chunks(node) -> List[str]:
    chunks = []
    seen: set = set()
    for item in node.find_all(["h1", "h2", "h3", "p", "li"]):
        text = normalize_text(item.get_text(" ", strip=True))
        if not text or _is_boilerplate_text(text) or _is_link_heavy_text(text):
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
    if len(units) < 3:
        return False
    noise_hits = sum(1 for p in units if _is_boilerplate_text(p))
    link_heavy_hits = sum(1 for p in units if _is_link_heavy_text(p))
    unique_ratio = len({normalize_for_match(p) for p in units}) / len(units)
    if noise_hits / len(units) >= 0.40:
        return False
    if link_heavy_hits / len(units) >= 0.30:
        return False
    if unique_ratio < 0.50:
        return False
    return True


def _split_text_units(text: str) -> List[str]:
    units = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [normalize_text(u) for u in units if normalize_text(u)]


def _unit_signature(text: str) -> str:
    from core.retrieval.search import tokenize

    terms = tokenize(text)
    if terms:
        return "|".join(sorted(set(terms))[:12])
    return normalize_for_match(text)[:120]


def _deduplicate_units(units: List[str], max_units: int = 140) -> List[str]:
    out = []
    seen_exact: set = set()
    seen_signature: set = set()
    for unit in units:
        normalized = normalize_text(unit)
        if not normalized or _is_boilerplate_text(normalized) or _is_link_heavy_text(normalized):
            continue
        exact_key = normalize_for_match(normalized)
        if exact_key in seen_exact:
            continue
        sig_key = _unit_signature(normalized)
        if sig_key in seen_signature:
            continue
        seen_exact.add(exact_key)
        seen_signature.add(sig_key)
        out.append(normalized)
        if len(out) >= max_units:
            break
    return out


def _finalize_clean_text(text: str) -> str:
    units = _split_text_units(text)
    cleaned = _deduplicate_units(units)
    return normalize_text(" ".join(cleaned))
