"""URL discovery tool for the Davivienda WPS portal.

Navigates the portal menu using Playwright and collects the URL
of each section so they can be added to SEED_URLS in .env.

Usage:
    python agent_browser.py
"""

import asyncio
import os
from urllib.parse import urlparse

from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

TARGET_URL = os.getenv(
    "TARGET_URL",
    "https://daviviendacorredorescolab.dvvapps.io",
)
_ALLOWED_DOMAIN = urlparse(TARGET_URL).netloc


def _is_internal(url: str) -> bool:
    """Return True if the URL belongs to the portal's domain."""
    try:
        return urlparse(url).netloc == _ALLOWED_DOMAIN
    except Exception:
        return False


async def discover_urls() -> list[str]:
    discovered: list[str] = []
    seen: set[str] = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(ignore_https_errors=True)

        # Load home page once to collect menu hrefs
        home = await context.new_page()
        print(f"Abriendo: {TARGET_URL}")
        await home.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        await home.wait_for_timeout(2000)

        hrefs: list[tuple[str, str]] = []
        anchors = await home.query_selector_all(
            ".menu-escritorio a[href], nav a[href]"
        )
        for anchor in anchors:
            href = await anchor.get_attribute("href")
            text = (await anchor.inner_text()).strip()
            if not href or href in ("#", "") or href.startswith("javascript"):
                continue
            if not href.startswith("http"):
                base = TARGET_URL.split("/wps/")[0] if "/wps/" in TARGET_URL else TARGET_URL
                href = base + href
            if href not in seen and text:
                seen.add(href)
                hrefs.append((text, href))

        await home.close()
        print(f"Links de menú encontrados: {len(hrefs)}\n")

        # Visit each link in a fresh page to avoid race conditions
        for text, href in hrefs:
            page = await context.new_page()
            try:
                await page.goto(href, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(800)
                final_url = page.url
                if final_url not in discovered:
                    discovered.append(final_url)
                    marker = "[OK]" if _is_internal(final_url) else "[ext]"
                    print(f"  {marker} {text[:50]}")
                    print(f"       {final_url}")
            except Exception as exc:
                print(f"  [--] {text[:50]}")
                print(f"       Error: {exc!s:.120}")
            finally:
                await page.close()

        await browser.close()

    return discovered


async def main() -> None:
    all_urls = await discover_urls()

    # Only include internal portal URLs in SEED_URLS
    internal = [u for u in all_urls if _is_internal(u)]

    if not internal:
        print("\nNo se descubrieron URLs internas.")
        return

    seed = ",".join(internal)
    print(f"\n{'='*60}")
    print(f"Total descubiertas: {len(all_urls)}  |  Internas: {len(internal)}")
    print(f"\nAgrega esto a tu .env:\n")
    print(f"SEED_URLS={seed}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())


