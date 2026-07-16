"""Playwright browser manager for handling CSR pages."""

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

_BROWSER = None
_PAGE_TIMEOUT = 30000  # 30 seconds


async def get_browser():
    """Get or create the Playwright browser instance."""
    global _BROWSER
    if _BROWSER is None or not _BROWSER.is_connected():
        from playwright.async_api import async_playwright

        p = await async_playwright().start()
        _BROWSER = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
            ],
        )
    return _BROWSER


async def fetch_page_html(url: str) -> str | None:
    """Fetch a page's rendered HTML using Playwright.

    Handles CSR pages by executing JavaScript and waiting for data to load.
    Returns None if browser is not available or page fails to load.
    """
    browser_available = os.environ.get("PLAYWRIGHT_ENABLED", "0") == "1"
    if not browser_available:
        return None

    try:
        browser = await get_browser()
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
            ),
            locale="zh-CN",
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=_PAGE_TIMEOUT)
            # Additional wait for data to finish rendering
            await asyncio.sleep(2)
            html = await page.content()
            return html
        except Exception as e:
            logger.warning(f"Playwright page load failed: {e}")
            return None
        finally:
            await page.close()
            await context.close()
    except Exception as e:
        logger.warning(f"Playwright browser error: {e}")
        return None


async def close_browser():
    """Close the Playwright browser instance."""
    global _BROWSER
    if _BROWSER:
        try:
            await _BROWSER.close()
        except Exception:
            pass
        _BROWSER = None
