import os
import time
from typing import List
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from core.document import Document
from core.scraping.fetcher import USER_AGENT, fetch_url, is_antibot_page
from core.scraping.parser import (
    extract_internal_links,
    extract_page_text,
    extract_personas_urls_from_raw,
)

load_dotenv()

_TARGET_URL = os.getenv("TARGET_URL", "https://daviviendacorredorescolab.dvvapps.io")
_parsed = urlparse(_TARGET_URL)

PERSONAS_URL: str = _TARGET_URL
BASE_URL: str = f"{_parsed.scheme}://{_parsed.netloc}"
ALLOWED_DOMAIN: str = _parsed.netloc
# Strip WPS portal-state token (!ut/p/z1/...) so content paths are in-scope.
_raw_path = _parsed.path.rstrip("/") or "/"
PERSONAS_PATH_PREFIX: str = _raw_path.split("/!ut/")[0] or "/"
SITEMAP_URL: str = f"{BASE_URL}/sitemap.xml"

PERSONAS_SEED_URLS: List[str] = [
    u.strip()
    for u in os.getenv("SEED_URLS", "").split(",")
    if u.strip()
]

_BLOCKED_SUFFIXES = (".pdf", ".zip", ".jpg", ".jpeg", ".png", ".gif", ".webp")


def is_allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc and not parsed.netloc.endswith(ALLOWED_DOMAIN):
        return False
    if parsed.path.lower().endswith(_BLOCKED_SUFFIXES):
        return False
    if "/download" in parsed.path.lower():
        return False
    return True


def is_personas_scope(url: str) -> bool:
    path = urlparse(url).path or "/"
    if PERSONAS_PATH_PREFIX == "/":
        return True
    return path.startswith(PERSONAS_PATH_PREFIX)


def parse_sitemap_urls(session: requests.Session, sitemap_url: str) -> List[str]:
    xml = fetch_url(session, sitemap_url)
    if not xml:
        return []
    soup = BeautifulSoup(xml, "xml")
    return [
        loc.get_text(strip=True)
        for loc in soup.find_all("loc")
        if loc.get_text(strip=True) and is_allowed_url(loc.get_text(strip=True))
    ]


def build_corpus(
    session: requests.Session,
    max_pages: int,
    delay_sec: float = 1.0,
) -> List[Document]:
    sitemap_urls = parse_sitemap_urls(session, SITEMAP_URL)

    urls: List[str] = [PERSONAS_URL]
    for u in PERSONAS_SEED_URLS:
        if u not in urls:
            urls.append(u)
    for u in sitemap_urls:
        if is_personas_scope(u) and u not in urls:
            urls.append(u)

    # Fallback 1: internal links from homepage when sitemap is sparse.
    if len(urls) < min(5, max_pages):
        personas_html = fetch_url(session, PERSONAS_URL)
        if personas_html:
            for u in extract_internal_links(personas_html, PERSONAS_URL):
                if is_personas_scope(u) and u not in urls:
                    urls.append(u)
                if len(urls) >= max_pages:
                    break

    # Fallback 2: regex extraction from raw HTML (catches paths embedded in scripts).
    if len(urls) < max_pages:
        for base_candidate in [PERSONAS_URL] + PERSONAS_SEED_URLS[:4]:
            base_html = fetch_url(session, base_candidate)
            if not base_html:
                continue
            for u in extract_personas_urls_from_raw(base_html, BASE_URL, PERSONAS_PATH_PREFIX):
                if u not in urls:
                    urls.append(u)
                if len(urls) >= max_pages:
                    break
            if len(urls) >= max_pages:
                break

    # Backfill with general sitemap pages if personas scope is too small.
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
            if not html or is_antibot_page(html):
                continue
            title, text = extract_page_text(html)
            if len(text) < 200:
                continue
            docs.append(Document(url=url, title=title, text=text))
            print(f"[{idx}/{len(urls)}] OK {url}")
            time.sleep(delay_sec)
        except requests.RequestException:
            continue

    return docs
