"""
crawler.py — production-grade async web crawler

Improvements over v1:
  - BFS queue instead of recursion (no stack overflow)
  - Async concurrency with semaphore (N pages in parallel)
  - URL normalization (strips fragments, sorts query params)
  - robots.txt support via urllib.robotparser
  - Configurable rate limiting (delay between requests)
  - Structured results with metadata (status, depth, title, crawl time)
  - Blocks images/fonts/stylesheets to speed up crawling
  - Graceful shutdown on Ctrl+C

Install:
    pip install playwright python-docx
    playwright install chromium
"""

import asyncio
import time
from collections import deque
from urllib.parse import urlparse, urlunparse, urlencode, parse_qsl, urljoin
from urllib.robotparser import RobotFileParser
from playwright.async_api import async_playwright, Browser


# ── Config ────────────────────────────────────────────────────────────────────

BLOCKED_DOMAINS = {
    "youtube.com", "twitter.com", "x.com", "facebook.com",
    "instagram.com", "linkedin.com", "t.co", "reddit.com",
}

BLOCKED_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".zip", ".tar", ".gz", ".mp4", ".mp3", ".wav", ".exe",
    ".css", ".js", ".ico", ".xml", ".json",
}


# ── URL helpers ───────────────────────────────────────────────────────────────

def normalize_url(url: str) -> str:
    """
    Normalize a URL so semantically identical URLs map to the same string:
      - Strip fragment  (#section)
      - Lowercase scheme and host
      - Sort query parameters
      - Remove trailing slash (except root /)
    """
    try:
        p = urlparse(url)
        path = p.path.rstrip("/") or "/"
        query = urlencode(sorted(parse_qsl(p.query)))
        return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", query, ""))
    except Exception:
        return url


def is_crawlable(url: str, base_domain: str) -> bool:
    """Return True if the URL should be queued for crawling."""
    try:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False

        hostname = parsed.hostname or ""

        # Same domain or subdomain only
        if not (hostname == base_domain or hostname.endswith(f".{base_domain}")):
            return False

        if any(blocked in hostname for blocked in BLOCKED_DOMAINS):
            return False

        # Skip static assets
        path = parsed.path.lower()
        if any(path.endswith(ext) for ext in BLOCKED_EXTENSIONS):
            return False

        return True
    except Exception:
        return False


# ── Robots.txt ────────────────────────────────────────────────────────────────

def load_robots(start_url: str) -> RobotFileParser:
    rp = RobotFileParser()
    parsed = urlparse(start_url)
    rp.set_url(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
    try:
        rp.read()
    except Exception:
        pass  # unreachable robots.txt → allow everything
    return rp


# ── Page scraper ──────────────────────────────────────────────────────────────

async def scrape_page(
    browser: Browser,
    url: str,
    semaphore: asyncio.Semaphore,
    delay: float,
) -> dict:
    """Open one page, extract text + links + title, return structured dict."""
    async with semaphore:
        await asyncio.sleep(delay)
        page = None
        start = time.monotonic()
        try:
            page = await browser.new_page()

            # Block heavy resources — images, fonts, stylesheets, media
            await page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ("image", "media", "font", "stylesheet")
                else route.continue_(),
            )

            response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            status = response.status if response else 0

            data = await page.evaluate("""() => ({
                title: document.title || '',
                text:  document.body?.innerText || '',
                links: Array.from(document.querySelectorAll('a[href]'))
                           .map(a => a.href)
                           .filter(h => h.startsWith('http')),
            })""")

            return {
                "url":          url,
                "title":        data["title"],
                "content":      data["text"],
                "links":        data["links"],
                "status":       status,
                "crawl_time_ms": round((time.monotonic() - start) * 1000),
                "error":        None,
            }

        except Exception as err:
            return {
                "url":          url,
                "title":        "",
                "content":      "",
                "links":        [],
                "status":       0,
                "crawl_time_ms": round((time.monotonic() - start) * 1000),
                "error":        str(err),
            }
        finally:
            if page:
                await page.close()


# ── BFS Crawler ───────────────────────────────────────────────────────────────

async def crawl_website(
    start_url: str,
    max_depth: int = 2,
    max_concurrency: int = 5,
    max_pages: int = 100,
    request_delay: float = 0.5,
    respect_robots: bool = True,
) -> list[dict]:
    """
    BFS-based async crawler.

    Args:
        start_url:       Seed URL.
        max_depth:       Max hops from the start URL.
        max_concurrency: Max browser pages open simultaneously.
        max_pages:       Hard cap on total pages crawled.
        request_delay:   Polite delay (seconds) between each page fetch.
        respect_robots:  Whether to honour robots.txt disallow rules.

    Returns:
        List of dicts: url, title, content, status, crawl_time_ms, error.
    """
    base_domain = urlparse(start_url).hostname or ""
    robots = load_robots(start_url) if respect_robots else None

    visited: set[str] = set()
    results: list[dict] = []

    # BFS queue — each entry is (normalized_url, depth)
    queue: deque[tuple[str, int]] = deque()
    seed = normalize_url(start_url)
    queue.append((seed, 0))
    visited.add(seed)

    semaphore = asyncio.Semaphore(max_concurrency)

    async with async_playwright() as p:
        browser = await p.chromium.launch()

        try:
            while queue and len(results) < max_pages:
                # Take everything currently in the queue as one concurrent batch
                batch = []
                while queue:
                    batch.append(queue.popleft())

                # Fan out — semaphore limits actual parallelism
                scraped = await asyncio.gather(
                    *[scrape_page(browser, url, semaphore, request_delay)
                      for url, _ in batch]
                )

                for (url, depth), page_data in zip(batch, scraped):
                    if page_data["error"]:
                        print(f"⚠️  [{depth}] {url} — {page_data['error']}")
                    else:
                        print(
                            f"✅  [{depth}] {url}  "
                            f"({page_data['crawl_time_ms']}ms, "
                            f"{len(page_data['links'])} links)"
                        )

                    # Store result without the raw links list
                    results.append({k: v for k, v in page_data.items() if k != "links"})

                    if len(results) >= max_pages:
                        break

                    # Enqueue child links for next BFS level
                    if depth < max_depth:
                        for raw_link in page_data["links"]:
                            resolved   = urljoin(url, raw_link)
                            normalized = normalize_url(resolved)

                            if normalized in visited:
                                continue
                            if not is_crawlable(normalized, base_domain):
                                continue
                            if robots and not robots.can_fetch("*", normalized):
                                print(f"🚫  robots.txt: {normalized}")
                                continue

                            visited.add(normalized)
                            queue.append((normalized, depth + 1))

        except asyncio.CancelledError:
            print("\n⛔  Crawl cancelled — saving partial results...")
        finally:
            await browser.close()

    print(f"\n📊  Done — {len(results)} pages crawled from {start_url}")
    return results


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    results = await crawl_website(
        start_url="https://www.websitecrawler.org/",  # replace with your target URL
        max_depth=2,
        max_concurrency=5,
        max_pages=100,
        request_delay=0.5,
        respect_robots=True,
    )
    print(results)


if __name__ == "__main__":
    asyncio.run(main())