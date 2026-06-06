# import asyncio
# from urllib.parse import urlparse
# from playwright.async_api import async_playwright
# # from save_results import save_results_to_word


# BLOCKED_DOMAINS = {
#     "youtube.com",
#     "twitter.com",
#     "x.com",
#     "facebook.com",
#     "instagram.com",
#     "linkedin.com",
#     "t.co",
# }


# async def crawl_website(start_url: str, max_depth: int = 2) -> list[dict]:
#     base_domain = urlparse(start_url).hostname
#     visited: set[str] = set()

#     async with async_playwright() as p:
#         browser = await p.chromium.launch()

#         async def crawl(url: str, depth: int) -> list[dict]:
#             if depth > max_depth or url in visited:
#                 return []
#             visited.add(url)

#             hostname = urlparse(url).hostname or ""

#             # Skip external domains
#             if hostname != base_domain:
#                 print(f"⏭️  Skipping external link: {url}")
#                 return []

#             # Skip blocked social domains
#             if any(blocked in hostname for blocked in BLOCKED_DOMAINS):
#                 print(f"⏭️  Skipping social link: {url}")
#                 return []

#             page = None
#             try:
#                 page = await browser.new_page()
#                 await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

#                 # Extract text and links from the page
#                 data = await page.evaluate("""() => {
#                     const text = document.body.innerText;
#                     const links = Array.from(document.querySelectorAll('a[href]'))
#                         .map(a => a.href)
#                         .filter(href => href.startsWith('http'));
#                     return { text, links };
#                 }""")

#                 await page.close()
#                 page = None

#                 results = [{"url": url, "content": data["text"]}]

#                 for link in data["links"]:
#                     print(f"Crawling {link}")
#                     results.extend(await crawl(link, depth + 1))

#                 return results

#             except Exception as err:
#                 print(f"⚠️  Failed to crawl {url}: {err}")
#                 if page:
#                     await page.close()
#                 return []

#         results = await crawl(start_url, 0)
#         await browser.close()
#         return results


# # ── Entry point ──────────────────────────────────────────────────────────────

# async def main():
#     url = "https://hitesh.ai"  # replace with your target URL
#     results = await crawl_website(url, max_depth=2)
#     print(f"\n✅ Crawled {len(results)} pages")
#     print(results)  # print first 3 results for sanity check
#     # save_results_to_word(results)  # mirrors JS saveResultsToWord(results)


# if __name__ == "__main__":
#     asyncio.run(main())