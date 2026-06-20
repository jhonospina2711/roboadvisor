import urllib.request

import cloudscraper
import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

ANTI_BOT_MARKERS = ("pardon our interruption", "noindex, nofollow")


def is_antibot_page(html: str) -> bool:
    h = html.lower()
    return any(marker in h for marker in ANTI_BOT_MARKERS)


def fetch_url(session: requests.Session, url: str, timeout: int = 20) -> str:
    try:
        resp = session.get(url, timeout=timeout)
        if resp.status_code == 200 and not is_antibot_page(resp.text):
            return resp.text
    except requests.RequestException:
        pass

    html = _fetch_cloudscraper(url=url, timeout=timeout)
    if html and not is_antibot_page(html):
        return html

    return _fetch_urllib(url=url, timeout=timeout)


def _fetch_cloudscraper(url: str, timeout: int = 20) -> str:
    try:
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        response = scraper.get(url, timeout=timeout)
        if response.status_code != 200:
            return ""
        return response.text
    except Exception:
        return ""


def _fetch_urllib(url: str, timeout: int = 20) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = response.read()
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""
