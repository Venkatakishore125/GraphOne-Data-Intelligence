import asyncio
import logging
from urllib.parse import urljoin, urlsplit

import aiohttp
import requests
from bs4 import BeautifulSoup


LOGGER = logging.getLogger("async_crawler")


def robots_allowed(url: str, user_agent: str = "GraphOneDataPipeline") -> bool:
    try:
        from urllib.robotparser import RobotFileParser
        parts = urlsplit(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.read()
        return parser.can_fetch(user_agent, url)
    except Exception as error:
        LOGGER.warning("robots.txt check failed for %s: %s", url, error)
        return False


async def fetch_text(session: aiohttp.ClientSession, url: str, timeout: float = 20.0) -> dict:
    if not robots_allowed(url):
        return {"url": url, "status": "ROBOTS_BLOCKED", "httpStatus": None, "text": "", "title": ""}
    try:
        async with session.get(url, timeout=timeout, allow_redirects=True) as response:
            status = response.status
            html = await response.text(errors="replace")
            soup = BeautifulSoup(html, "html.parser")
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = " ".join(soup.stripped_strings)
            return {"url": str(response.url), "status": "OK" if 200 <= status < 300 else "HTTP_ERROR",
                    "httpStatus": status, "text": text[:50000], "title": title}
    except asyncio.TimeoutError:
        return {"url": url, "status": "TIMEOUT", "httpStatus": None, "text": "", "title": ""}
    except aiohttp.ClientError as error:
        return {"url": url, "status": "FETCH_ERROR", "httpStatus": None, "text": "", "title": "", "error": str(error)}


async def crawl_urls(urls: list[str], concurrency: int = 4) -> list[dict]:
    connector = aiohttp.TCPConnector(limit=concurrency)
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout,
                                     headers={"User-Agent": "GraphOneDataPipeline/1.0"}) as session:
        semaphore = asyncio.Semaphore(concurrency)

        async def guarded(url):
            async with semaphore:
                return await fetch_text(session, url)

        return await asyncio.gather(*(guarded(url) for url in urls))
