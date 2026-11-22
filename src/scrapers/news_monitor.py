import json
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup
from urllib.robotparser import RobotFileParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


NEWS_SOURCES = [
    {"name": "MIT Technology Review", "url": "https://www.technologyreview.com/feed/"},
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/tag/artificial-intelligence/feed/"},
    {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml"},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/technology-lab"},
    {"name": "OpenAI News", "url": "https://openai.com/news/rss.xml"},
    {"name": "Google AI", "url": "https://blog.google/innovation-and-ai/technology/ai/rss/"},
]


def normalize_datetime(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except Exception:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def canonical_url(value: str) -> str:
    if not value:
        return ""
    parts = urlsplit(str(value).strip())
    if not parts.scheme or not parts.netloc:
        return str(value).strip()
    query = [
        (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() not in {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "fbclid", "gclid"}
    ]
    path = parts.path.rstrip("/") or "/"
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(query), ""))


def fetch_available_text(url: str, summary: str) -> str:
    if not url:
        return " ".join(summary.split())[:50000]
    try:
        parts = urlsplit(url)
        parser = RobotFileParser()
        parser.set_url(f"{parts.scheme}://{parts.netloc}/robots.txt")
        parser.read()
        if not parser.can_fetch("GraphOneDataPipeline", url):
            return " ".join(summary.split())[:50000]
        response = requests.get(url, timeout=20,
                                headers={"User-Agent": "GraphOneDataPipeline/1.0"})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        text = " ".join(soup.stripped_strings)
        return text[:50000] if text else " ".join(summary.split())[:50000]
    except Exception:
        return " ".join(summary.split())[:50000]


def collect_news(window_hours: int = 24, output_dir: Path = Path("data")) -> tuple[list[dict], list[dict]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    now = datetime.now(timezone.utc)
    records = []
    errors = []
    for source in NEWS_SOURCES:
        try:
            parsed = feedparser.parse(source["url"])
            if parsed.bozo and not parsed.entries:
                raise RuntimeError(str(parsed.bozo_exception))
            for entry in parsed.entries:
                raw_date = entry.get("published") or entry.get("updated")
                published = normalize_datetime(raw_date)
                if not published or published < cutoff or published > now:
                    continue
                summary = entry.get("summary") or entry.get("description") or ""
                full_text = fetch_available_text(entry.get("link", ""), summary)
                records.append({
                    "title": entry.get("title", "").strip(),
                    "url": entry.get("link", ""),
                    "sourceName": source["name"],
                    "sourceUrl": source["url"],
                    "publishedAt": published.isoformat(),
                    "collectedAt": datetime.now(timezone.utc).isoformat(),
                    "fullText": full_text,
                    "dateFilter": f"published within {window_hours} hours",
                })
        except Exception as error:
            errors.append({"sourceName": source["name"], "sourceUrl": source["url"], "error": str(error)})

    unique = {}
    for record in records:
        key = canonical_url(record["url"])
        if key:
            unique.setdefault(key, record)
    result = list(unique.values())
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "news_last_24h.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "news_last_24h_errors.json").write_text(json.dumps(errors, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result, errors
