import json
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup
from urllib.robotparser import RobotFileParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


JOB_SOURCES = [
    {"name": "Arbeitnow", "url": "https://www.arbeitnow.com/api/job-board-api"},
    {"name": "RemoteOK", "url": "https://remoteok.com/api"},
    {"name": "Remotive", "url": "https://remotive.com/api/remote-jobs?category=software-dev"},
    {"name": "Himalayas", "url": "https://himalayas.app/jobs/api"},
    {"name": "Jobicy", "url": "https://jobicy.com/api/v2/remote-jobs"},
]

AI_JOB_TERMS = (
    "artificial intelligence", " machine learning", "deep learning", " ai ",
    "llm", "data scientist", "ml engineer", "ai engineer", "prompt",
    "computer vision", "nlp", "natural language", "generative",
)


def is_ai_job(title: str, description: str, tags=None) -> bool:
    text = " ".join([
        str(title or ""),
        str(description or ""),
        " ".join(str(tag) for tag in (tags or [])),
    ]).casefold()
    text = f" {text} "
    return any(term in text for term in AI_JOB_TERMS)


def normalize_datetime(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(str(value))
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


def collect_jobs(window_hours: int = 24, output_dir: Path = Path("data")) -> tuple[list[dict], list[dict]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    now = datetime.now(timezone.utc)
    records = []
    errors = []
    for source in JOB_SOURCES:
        try:
            response = requests.get(
                source["url"],
                timeout=30,
                headers={"User-Agent": "GraphOneDataPipeline/1.0"},
            )
            response.raise_for_status()
            data = response.json()

            if source["name"] == "Arbeitnow":
                entries = data.get("data", [])
                for job in entries:
                    raw = job.get("created_at")
                    published = datetime.fromtimestamp(raw, tz=timezone.utc) if isinstance(raw, (int, float)) else normalize_datetime(raw)
                    if not published or published < cutoff or published > now:
                        continue
                    title, description = job.get("title", ""), job.get("description", "")
                    if not is_ai_job(title, description, job.get("tags", [])):
                        continue
                    records.append({
                        "title": title,
                        "company": job.get("company_name", ""),
                        "location": job.get("location", ""),
                        "url": job.get("url", ""),
                        "sourceName": source["name"],
                        "sourceUrl": source["url"],
                        "publishedAt": published.isoformat(),
                        "collectedAt": datetime.now(timezone.utc).isoformat(),
                        "fullText": fetch_available_text(job.get("url", ""), description),
                        "dateFilter": f"published within {window_hours} hours",
                    })

            elif source["name"] == "RemoteOK":
                entries = data[1:] if isinstance(data, list) else []
                for job in entries:
                    raw = job.get("date") or job.get("epoch")
                    if isinstance(raw, (int, float)):
                        published = datetime.fromtimestamp(raw, tz=timezone.utc)
                    else:
                        published = normalize_datetime(raw)
                    if not published or published < cutoff or published > now:
                        continue
                    title, description = job.get("position", ""), job.get("description", "")
                    if not is_ai_job(title, description, job.get("tags", [])):
                        continue
                    url = job.get("url") or (f"https://remoteok.com/remote-jobs/{job.get('id')}" if job.get("id") else "")
                    records.append({
                        "title": title,
                        "company": job.get("company", ""),
                        "location": job.get("location", "") or "Remote",
                        "url": url,
                        "sourceName": source["name"],
                        "sourceUrl": source["url"],
                        "publishedAt": published.isoformat(),
                        "collectedAt": datetime.now(timezone.utc).isoformat(),
                        "fullText": fetch_available_text(url, description),
                        "dateFilter": f"published within {window_hours} hours",
                    })

            elif source["name"] == "Remotive":
                entries = data.get("jobs", [])
                for job in entries:
                    published = normalize_datetime(job.get("publication_date"))
                    if not published or published < cutoff or published > now:
                        continue
                    title, description = job.get("title", ""), job.get("description", "")
                    if not is_ai_job(title, description, job.get("tags", [])):
                        continue
                    url = job.get("url", "")
                    records.append({
                        "title": title,
                        "company": job.get("company_name", ""),
                        "location": job.get("candidate_required_location", "") or "Remote",
                        "url": url,
                        "sourceName": source["name"],
                        "sourceUrl": source["url"],
                        "publishedAt": published.isoformat(),
                        "collectedAt": datetime.now(timezone.utc).isoformat(),
                        "fullText": fetch_available_text(url, description),
                        "dateFilter": f"published within {window_hours} hours",
                    })

            elif source["name"] == "Himalayas":
                entries = data.get("jobs", [])
                for job in entries:
                    raw = job.get("pubDate")
                    published = datetime.fromtimestamp(raw, tz=timezone.utc) if isinstance(raw, (int, float)) else normalize_datetime(raw)
                    if not published or published < cutoff or published > now:
                        continue
                    title, description = job.get("title", ""), job.get("description", "")
                    if not is_ai_job(title, description, job.get("categories", []) + job.get("parentCategories", [])):
                        continue
                    url = job.get("applicationLink") or job.get("url", "")
                    records.append({
                        "title": title,
                        "company": job.get("companyName", ""),
                        "location": ", ".join(job.get("locationRestrictions", []) or []) or "Remote",
                        "url": url,
                        "sourceName": source["name"],
                        "sourceUrl": source["url"],
                        "publishedAt": published.isoformat(),
                        "collectedAt": datetime.now(timezone.utc).isoformat(),
                        "fullText": fetch_available_text(url, description),
                        "dateFilter": f"published within {window_hours} hours",
                    })

            elif source["name"] == "Jobicy":
                entries = data.get("jobs", [])
                for job in entries:
                    raw = job.get("pubDate")
                    published = datetime.fromtimestamp(raw, tz=timezone.utc) if isinstance(raw, (int, float)) else normalize_datetime(raw)
                    if not published or published < cutoff or published > now:
                        continue
                    title = job.get("jobTitle", "")
                    description = job.get("jobDescription", "")
                    if not is_ai_job(title, description, job.get("jobIndustry", [])):
                        continue
                    url = job.get("url", "")
                    records.append({
                        "title": title,
                        "company": job.get("companyName", ""),
                        "location": job.get("jobGeo", "") or "Remote",
                        "url": url,
                        "sourceName": source["name"],
                        "sourceUrl": source["url"],
                        "publishedAt": published.isoformat(),
                        "collectedAt": datetime.now(timezone.utc).isoformat(),
                        "fullText": fetch_available_text(url, description),
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
    (output_dir / "jobs_last_24h.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "jobs_last_24h_errors.json").write_text(json.dumps(errors, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result, errors
