from __future__ import annotations

import copy
import csv
import hashlib
import ipaddress
import json
import os
import re
import shutil
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
INPUT = DATA / "products_new_sources_candidates.json"
EXPECTED_COUNT = 803
USER_AGENT = "GraphOne-Data-Intelligence/1.0"
TIMEOUT = (5, 12)
MAX_PAGE_BYTES = 2_000_000
WORKERS = 8
GLOBAL_REQUEST_INTERVAL = 0.25
HOST_REQUEST_INTERVAL = 1.0

OUTPUTS = {
    "review_json": DATA / "products_803_final_review.json",
    "review_csv": DATA / "products_803_final_review.csv",
    "approved": DATA / "products_803_approved.json",
    "manual": DATA / "products_803_manual_check.json",
    "rejected": DATA / "products_803_rejected.json",
    "report": DATA / "products_803_review_report.txt",
}

PROTECTED_FILES = [
    DATA / "products.json",
    DATA / "products.csv",
    DATA / "products_merged_review.json",
    INPUT,
    DATA / "products_new_sources_review.csv",
]

EXISTING_JSON_FILES = [
    "products.json",
    "products_merged_review.json",
    "products_merge_review.json",
    "products_scraped.json",
    "mydentify_approved_products.json",
    "ignlab_normalized_products.json",
]
EXISTING_CSV_FILES = [
    "products.csv",
    "mydentify_approved_products.csv",
    "ignlab_final_review.csv",
]

AI_PATTERNS = [
    ("machine learning", re.compile(r"\bmachine learning\b|\bdeep learning\b", re.I)),
    ("large language model", re.compile(r"\blarge language models?\b|\bLLMs?\b", re.I)),
    ("generative AI", re.compile(r"\bgenerative\s+AI\b", re.I)),
    ("AI agent", re.compile(r"\bAI[- ]agents?\b", re.I)),
    ("AI assistant", re.compile(r"\bAI[- ]assistants?\b|\bAI copilot\b", re.I)),
    ("AI chatbot", re.compile(r"\bAI[- ]chatbots?\b|\bAI chat assistant\b", re.I)),
    ("AI-powered functionality", re.compile(r"\bAI[- ](?:powered|driven|based|enabled|native)\b(?:\s+\w+){0,3}", re.I)),
    ("AI generation or analysis", re.compile(r"\bAI\s+(?:generates?|creates?|edits?|summari[sz]es?|analy[sz]es?|translates?|recommends?|predicts?|detects?|classifies?|transcribes?|automates?)\b", re.I)),
    ("AI-specific product", re.compile(r"\bAI[- ](?:image|video|voice|music|code|writing|design|search|translation|tutor|medical|data|document)\b", re.I)),
    ("computer vision", re.compile(r"\bcomputer vision\b", re.I)),
    ("natural language processing", re.compile(r"\bnatural language processing\b|\bNLP\b", re.I)),
    ("text-to-image or video", re.compile(r"\btext[- ]to[- ](?:image|video)\b", re.I)),
    ("AI speech synthesis", re.compile(r"\bAI[- ](?:voice|speech|transcription|transcription)\b|\btext[- ]to[- ]speech\b", re.I)),
]

GENERIC_TOKENS = {
    "ai", "tool", "tools", "product", "platform", "software", "service",
    "app", "application", "online", "free", "best", "new", "review",
    "reviews", "use", "cases", "pricing", "alternatives", "generator",
    "maker", "assistant", "agent", "chatbot", "powered", "based",
    "artificial", "intelligence", "the", "and", "for", "with", "by",
    "from", "your", "my", "one", "all", "in", "on", "to", "of",
}
STOPWORDS = GENERIC_TOKENS | {
    "a", "an", "is", "are", "that", "this", "it", "its", "as", "at",
    "be", "can", "will", "or", "into", "their", "they", "you", "we",
    "our", "who", "what", "when", "where", "how", "which", "than",
    "more", "most", "every", "each", "any", "all", "about", "after",
    "before", "while", "using", "use", "users", "user", "based", "helps",
    "help", "make", "makes", "create", "creates", "turn", "turns",
    "build", "builds", "designed", "simple", "easy", "fast", "quick",
}

NON_PRODUCT_AIXPLORIA_SLUGS = {
    "ultimate-list-ai", "categories-ai", "tutorials-video-ai-free-lessons",
    "last-ai", "free-ai", "ai-news-today", "bonus-extras-ai", "add-ai",
    "aixploria-newsletter", "verified-ai-tools", "ai-freemium", "ai-paid",
    "ai-free-trial", "disclosure", "about", "contact", "ai-deals",
}

SPECIAL_MISMATCHES = [
    ("benchmark email", {"atomicmail.io"}, "Benchmark Email points to Atomic Mail."),
    ("keychain", {"accio.com"}, "Keychain points to Accio, a different product identity."),
    ("ai humanizer quillbot", {"lenso.ai"}, "AI Humanizer QuillBot points to Lenso, an unrelated image-search product."),
    ("turnitin", {"easemate.ai"}, "Turnitin points to EaseMate AI, a different product."),
    ("speech synthesis", {"qwen.ai"}, "Speech Synthesis points to a Qwen blog page, not a matching product page."),
    ("deepl", {"palabra.ai"}, "DeepL points to Palabra.ai, a different product identity."),
    ("mailerlite", {"getproton.me", "proton.me"}, "MailerLite points to a Proton affiliate destination."),
    ("gemini 4 hydrogen", {"kimi.ai"}, "Gemini 4 Hydrogen points to a Kimi page, a different product identity."),
    ("amw suite", {"vmake.ai"}, "AMW Suite points to Vmake, a different product identity."),
]

_rate_lock = threading.Lock()
_next_global_request = 0.0
_next_host_request: dict[str, float] = {}
_robots_lock = threading.Lock()
_robots_cache: dict[str, tuple[RobotFileParser | None, str | None]] = {}
_stats_lock = threading.Lock()
_stats = Counter()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_url(value: object) -> str | None:
    try:
        parsed = urlsplit(str(value or "").strip())
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not host:
        return None
    host = host.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return None
    try:
        address = ipaddress.ip_address(host)
        if not address.is_global:
            return None
    except ValueError:
        pass
    netloc = host
    if port and port not in {80, 443}:
        netloc = f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def host_for(url: str | None) -> str:
    try:
        return (urlsplit(url or "").hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def origin_for(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def clean_product_name(name: object) -> str:
    value = str(name or "").strip()
    value = re.sub(
        r"\s+(?:AI\s+)?Reviews?:\s*Use Cases,\s*Pricing\s*&\s*Alternatives.*$",
        "",
        value,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", value).strip(" -|:")


def words(value: object) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(value or "").casefold())


def normalized_name(value: object) -> str:
    return " ".join(words(clean_product_name(value)))


def identity_tokens(value: object) -> set[str]:
    return {
        token for token in words(clean_product_name(value))
        if len(token) >= 3 and token not in GENERIC_TOKENS and not token.isdigit()
    }


def meaningful_tokens(value: object) -> set[str]:
    return {
        token for token in words(value)
        if len(token) >= 3 and token not in STOPWORDS and not token.isdigit()
    }


def product_records(value: object, dataset: str):
    if isinstance(value, list):
        for item in value:
            yield from product_records(item, dataset)
        return
    if not isinstance(value, dict):
        return
    content = value.get("content")
    if isinstance(content, dict):
        name = content.get("productName") or content.get("name")
        website = content.get("website") or content.get("url")
        if name or website:
            yield {
                "productName": str(name or ""),
                "website": str(website or ""),
                "dataset": dataset,
            }
        return
    name = value.get("productName") or value.get("name")
    website = value.get("website") or value.get("url")
    if name or website:
        yield {
            "productName": str(name or ""),
            "website": str(website or ""),
            "dataset": dataset,
        }
        return
    for nested in value.values():
        if isinstance(nested, (list, dict)):
            yield from product_records(nested, dataset)


def load_existing_catalog() -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    by_domain: dict[str, list[dict]] = defaultdict(list)
    by_name: dict[str, list[dict]] = defaultdict(list)
    for filename in EXISTING_JSON_FILES:
        path = DATA / filename
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as stream:
            records = json.load(stream)
        for record in product_records(records, filename):
            domain = host_for(normalize_url(record["website"]))
            name = normalized_name(record["productName"])
            if domain:
                by_domain[domain].append(record)
            if name:
                by_name[name].append(record)
    for filename in EXISTING_CSV_FILES:
        path = DATA / filename
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                decision = str(row.get("decision") or "").strip().upper()
                if decision and decision not in {"APPROVE", "APPROVED", "ACCEPT"}:
                    continue
                record = {
                    "productName": str(row.get("productName") or row.get("name") or ""),
                    "website": str(row.get("website") or row.get("url") or ""),
                    "dataset": filename,
                }
                domain = host_for(normalize_url(record["website"]))
                name = normalized_name(record["productName"])
                if domain:
                    by_domain[domain].append(record)
                if name:
                    by_name[name].append(record)
    return by_domain, by_name


def candidate_duplicates(
    candidates: list[dict],
    existing_domains: dict[str, list[dict]],
    existing_names: dict[str, list[dict]],
) -> list[dict]:
    by_domain: dict[str, list[int]] = defaultdict(list)
    by_name: dict[str, list[int]] = defaultdict(list)
    prepared = []
    for index, candidate in enumerate(candidates):
        domain = host_for(normalize_url(candidate.get("website")))
        name = normalized_name(candidate.get("productName"))
        if domain:
            by_domain[domain].append(index)
        if name:
            by_name[name].append(index)
        prepared.append((domain, name))

    results = []
    for index, (domain, name) in enumerate(prepared):
        matches = []
        exact_existing = []
        same_domain = existing_domains.get(domain, []) if domain else []
        same_name = existing_names.get(name, []) if name else []
        for record in same_domain + same_name:
            ref = {
                "productName": record["productName"],
                "website": record["website"],
                "dataset": record["dataset"],
            }
            if ref not in matches:
                matches.append(ref)
            if (
                domain and name
                and host_for(normalize_url(record["website"])) == domain
                and normalized_name(record["productName"]) == name
            ):
                exact_existing.append(ref)

        same_candidate_domain = by_domain.get(domain, []) if domain else []
        same_candidate_name = by_name.get(name, []) if name else []
        other_domain = [i for i in same_candidate_domain if i != index]
        other_name = [i for i in same_candidate_name if i != index]
        if exact_existing:
            status = "DUPLICATE_EXISTING"
        elif other_domain and other_name:
            status = "DUPLICATE_CANDIDATE_GROUP"
            matches.extend({
                "productName": candidates[i].get("productName", ""),
                "website": candidates[i].get("website", ""),
                "dataset": "products_new_sources_candidates.json",
            } for i in other_domain + other_name)
        elif other_name:
            status = "NAME_COLLISION_CANDIDATE"
            matches.extend({
                "productName": candidates[i].get("productName", ""),
                "website": candidates[i].get("website", ""),
                "dataset": "products_new_sources_candidates.json",
            } for i in other_name)
        elif other_domain:
            status = "DOMAIN_COLLISION_CANDIDATE"
            matches.extend({
                "productName": candidates[i].get("productName", ""),
                "website": candidates[i].get("website", ""),
                "dataset": "products_new_sources_candidates.json",
            } for i in other_domain)
        elif same_domain:
            status = "DOMAIN_MATCH_EXISTING"
        elif same_name:
            status = "NAME_MATCH_EXISTING"
        else:
            status = "UNIQUE"
        results.append({"status": status, "matches": matches})
    return results


def validate_source_provenance(candidate: dict) -> tuple[str, str]:
    provenance = candidate.get("sourceProvenance")
    if not isinstance(provenance, list) or not provenance:
        return "MISSING", "No source provenance was recorded."
    for item in provenance:
        source = str(item.get("sourceName") or "").strip().casefold()
        source_url = normalize_url(item.get("sourceListingUrl"))
        if not source_url:
            return "INVALID", "A source listing URL is missing or invalid."
        parsed = urlsplit(source_url)
        host = host_for(source_url)
        path = parsed.path.rstrip("/").casefold()
        if source == "futurepedia":
            valid = host == "futurepedia.io" and path.startswith("/tool/")
        elif source == "futuretools":
            valid = host == "futuretools.io" and path.startswith("/tools/")
        elif source == "aixploria":
            parts = [part for part in path.split("/") if part]
            valid = (
                host == "aixploria.com"
                and len(parts) == 2
                and parts[0] == "en"
                and parts[1] not in NON_PRODUCT_AIXPLORIA_SLUGS
            )
            if host == "aixploria.com" and len(parts) == 2 and parts[1] == "ai-deals":
                return "IRRELEVANT", "The source URL is an AI deals page, not a product listing."
        else:
            return "UNKNOWN_SOURCE", f"Unrecognized source name: {item.get('sourceName')!r}."
        if not valid:
            return "INVALID", f"Source URL does not match the recorded {item.get('sourceName')} listing format."
    return "VALID", "Source provenance uses a known public product-listing URL."


def throttle_request(host: str) -> None:
    global _next_global_request
    with _rate_lock:
        now = time.monotonic()
        due = max(_next_global_request, _next_host_request.get(host, 0.0))
        wait = max(0.0, due - now)
        start = now + wait
        _next_global_request = start + GLOBAL_REQUEST_INTERVAL
        _next_host_request[host] = start + HOST_REQUEST_INTERVAL
    if wait:
        time.sleep(wait)


def validate_request_url(url: str) -> None:
    normalized = normalize_url(url)
    if not normalized:
        raise ValueError(f"Unsafe or invalid public HTTP(S) URL: {url!r}")


def robots_allowed(url: str) -> tuple[bool | None, str]:
    origin = origin_for(url)
    with _robots_lock:
        cached = _robots_cache.get(origin)
    if cached is None:
        robots_url = origin.rstrip("/") + "/robots.txt"
        try:
            validate_request_url(robots_url)
            throttle_request(host_for(robots_url))
            with _stats_lock:
                _stats["httpRequests"] += 1
                _stats["robotsRequests"] += 1
            response = requests.get(
                robots_url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/plain,*/*;q=0.5"},
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            status = response.status_code
            body = response.text if status == 200 else ""
            response.close()
            if status == 200:
                parser = RobotFileParser()
                parser.set_url(robots_url)
                parser.parse(body.splitlines())
                result = (parser, "ROBOTS_OK")
            elif status in {404, 410}:
                result = (RobotFileParser(), "ROBOTS_NOT_PUBLISHED")
            elif status in {401, 403, 429}:
                result = (None, f"ROBOTS_HTTP_{status}")
            else:
                result = (None, f"ROBOTS_UNKNOWN_HTTP_{status}")
        except (requests.RequestException, ValueError) as error:
            result = (None, "ROBOTS_ERROR: " + str(error))
        with _robots_lock:
            _robots_cache[origin] = result
        cached = result

    parser, status = cached
    if parser is None:
        return None, status
    try:
        allowed = parser.can_fetch(USER_AGENT, url)
    except Exception as error:
        return None, "ROBOTS_PARSE_ERROR: " + str(error)
    return allowed, status


def read_limited_response(response: requests.Response) -> str:
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=16384):
        if not chunk:
            continue
        remaining = MAX_PAGE_BYTES - total
        if remaining <= 0:
            break
        chunks.append(chunk[:remaining])
        total += min(len(chunk), remaining)
        if total >= MAX_PAGE_BYTES:
            break
    encoding = response.encoding or "utf-8"
    return b"".join(chunks).decode(encoding, errors="replace")


def fetch_page(url: object) -> dict:
    checked_at = utc_now()
    requested = normalize_url(url)
    result = {
        "checkedAt": checked_at,
        "requestedUrl": requested,
        "finalUrl": None,
        "verificationStatus": "FETCH_ERROR",
        "httpStatus": None,
        "pageTitle": "",
        "metaDescription": "",
        "h1": "",
        "coreText": "",
        "aiEvidence": [],
        "strongAiEvidence": False,
        "errorDetail": "",
        "robotsStatus": "",
        "redirectedAcrossDomains": False,
    }
    if not requested:
        result.update({
            "verificationStatus": "MISSING_OR_INVALID_URL",
            "errorDetail": "No valid public HTTP(S) website URL was present.",
        })
        return result

    current = requested
    visited = set()
    initial_host = host_for(requested)
    for _ in range(7):
        if current in visited:
            result.update({
                "verificationStatus": "REDIRECT_LOOP",
                "finalUrl": current,
                "errorDetail": "Redirect loop detected.",
            })
            return result
        visited.add(current)
        try:
            validate_request_url(current)
            allowed, robots_status = robots_allowed(current)
            result["robotsStatus"] = robots_status
            if allowed is None:
                result.update({
                    "verificationStatus": "ROBOTS_UNVERIFIED",
                    "finalUrl": current,
                    "errorDetail": robots_status,
                })
                return result
            if not allowed:
                result.update({
                    "verificationStatus": "ROBOTS_DISALLOWED",
                    "finalUrl": current,
                    "errorDetail": f"robots.txt disallows access to {urlsplit(current).path or '/'}",
                })
                return result
            throttle_request(host_for(current))
            with _stats_lock:
                _stats["httpRequests"] += 1
                _stats["websiteRequests"] += 1
            response = requests.get(
                current,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                },
                timeout=TIMEOUT,
                allow_redirects=False,
                stream=True,
            )
            status = response.status_code
            result["httpStatus"] = status
            if status in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    result.update({
                        "verificationStatus": "REDIRECT_WITHOUT_LOCATION",
                        "finalUrl": current,
                        "errorDetail": "HTTP redirect did not include a Location header.",
                    })
                    return result
                target = normalize_url(urljoin(current, location))
                if not target:
                    result.update({
                        "verificationStatus": "UNSAFE_REDIRECT",
                        "finalUrl": current,
                        "errorDetail": "Redirect target was not a valid public HTTP(S) URL.",
                    })
                    return result
                if host_for(target) != initial_host:
                    result["redirectedAcrossDomains"] = True
                current = target
                continue
            html = read_limited_response(response)
            result["finalUrl"] = current
            response.close()
            if status < 200 or status >= 300:
                result["verificationStatus"] = "HTTP_ERROR"
                result["errorDetail"] = f"Official website returned HTTP {status}."
                return result
            result["verificationStatus"] = "HTTP_OK"
            soup = BeautifulSoup(html, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""

            def meta(*selectors: tuple[str, str]) -> str:
                for attribute, key in selectors:
                    tag = soup.find("meta", attrs={attribute: key})
                    if tag and tag.get("content"):
                        return tag["content"].strip()
                return ""

            description = meta(("name", "description"), ("property", "og:description"))
            site_name = meta(("property", "og:site_name"), ("name", "application-name"))
            for node in soup.select("script,style,noscript,svg,iframe,nav,footer,aside"):
                node.decompose()
            headings = [
                node.get_text(" ", strip=True)
                for node in soup.find_all(["h1", "h2", "h3"])
                if node.get_text(" ", strip=True)
            ]
            h1 = " ".join(
                node.get_text(" ", strip=True)
                for node in soup.find_all("h1")
                if node.get_text(" ", strip=True)
            )
            main = soup.find("main") or soup.find("article") or soup.body or soup
            core_text = " ".join(main.stripped_strings)
            result.update({
                "pageTitle": title[:500],
                "metaDescription": description[:1500],
                "h1": h1[:1000],
                "coreText": core_text[:50000],
            })
            identity_text = " ".join([title, h1, site_name, *headings[:12]])
            evidence_sections = [
                ("page title", title),
                ("meta description", description),
                ("headings", " ".join(headings)),
                ("visible page text", core_text[:30000]),
            ]
            evidence = []
            seen_labels = set()
            for label, pattern in AI_PATTERNS:
                for section_name, section_text in evidence_sections:
                    match = pattern.search(section_text)
                    if not match:
                        continue
                    if label in seen_labels:
                        break
                    start = max(0, match.start() - 90)
                    end = min(len(section_text), match.end() + 120)
                    evidence.append({
                        "term": label,
                        "section": section_name,
                        "snippet": re.sub(r"\s+", " ", section_text[start:end]).strip(),
                        "strength": "strong",
                    })
                    seen_labels.add(label)
                    break
            result["aiEvidence"] = evidence
            result["strongAiEvidence"] = bool(evidence)
            result["identityText"] = identity_text[:2500]
            result["siteName"] = site_name[:300]
            return result
        except (requests.RequestException, ValueError) as error:
            result.update({
                "verificationStatus": "FETCH_ERROR",
                "finalUrl": current,
                "errorDetail": str(error)[:1000],
            })
            return result
    result.update({
        "verificationStatus": "TOO_MANY_REDIRECTS",
        "finalUrl": current,
        "errorDetail": "More than six redirects.",
    })
    return result


def identity_check(product_name: object, verification: dict) -> tuple[str, list[str]]:
    candidate_tokens = identity_tokens(product_name)
    if not candidate_tokens:
        return "UNKNOWN", []
    title_tokens = identity_tokens(verification.get("identityText"))
    host_tokens = identity_tokens(host_for(verification.get("finalUrl")))
    direct_matches = candidate_tokens & title_tokens
    domain_matches = candidate_tokens & host_tokens
    matched = sorted(direct_matches | domain_matches)
    if direct_matches:
        return "MATCH", matched
    if domain_matches:
        title_has_other_brand = bool(title_tokens) and not bool(title_tokens & candidate_tokens)
        if title_has_other_brand:
            return "MISMATCH", []
        return "MATCH", matched
    identity_text = str(verification.get("identityText") or "")
    if identity_text and title_tokens:
        return "MISMATCH", []
    return "UNKNOWN", []


def description_match(description: object, core_text: object) -> tuple[bool, list[str]]:
    described = meaningful_tokens(description)
    page = meaningful_tokens(core_text)
    if len(described) < 3 or not page:
        return False, []
    overlap = sorted(described & page)
    threshold = 2 if len(described) <= 8 else 3
    matched = len(overlap) >= threshold and len(overlap) / max(1, len(described)) >= 0.08
    return matched, overlap[:20]


def has_ai_signal(text: object) -> bool:
    return any(pattern.search(str(text or "")) for _, pattern in AI_PATTERNS)


def special_mismatch(product_name: object, website: object) -> str | None:
    name = normalized_name(product_name)
    host = host_for(normalize_url(website))
    for expected_name, hosts, reason in SPECIAL_MISMATCHES:
        if name == expected_name and any(host == item or host.endswith("." + item) for item in hosts):
            return reason
    return None


def classify(
    candidate: dict,
    verification: dict,
    duplicate: dict,
    source_status: str,
    source_reason: str,
    matched_description_terms: list[str],
    cached_identity_status: str | None = None,
    cached_description_match: bool | None = None,
) -> tuple[str, str, str]:
    name = candidate.get("productName")
    website = candidate.get("website")
    mismatch = special_mismatch(name, website)
    if mismatch:
        return "REJECT", mismatch, "PRODUCT_IDENTITY_MISMATCH"
    if source_status == "IRRELEVANT":
        return "REJECT", source_reason, "IRRELEVANT_SOURCE"
    if duplicate["status"] == "DUPLICATE_EXISTING":
        return "REJECT", "Exact product name and website domain already exist in an approved/existing dataset.", "DUPLICATE"
    if duplicate["status"] == "DUPLICATE_CANDIDATE_GROUP":
        return "REJECT", "This record duplicates a candidate with the same normalized name and website domain.", "DUPLICATE"

    status = verification.get("httpStatus")
    state = verification.get("verificationStatus")
    if status in {404, 410}:
        return "REJECT", f"Official website returned HTTP {status}.", "INVALID_WEBSITE"
    if state != "HTTP_OK" or status is None or not 200 <= status < 300:
        return "MANUAL CHECK", (
            "Official site could not be fully checked; no conclusion was inferred. "
            + str(verification.get("errorDetail") or state or "HTTP verification incomplete.")
        ), state or "INCOMPLETE"
    if source_status != "VALID":
        return "MANUAL CHECK", source_reason, "SOURCE_UNVERIFIED"
    if duplicate["status"] in {
        "DOMAIN_MATCH_EXISTING", "NAME_MATCH_EXISTING",
        "NAME_COLLISION_CANDIDATE", "DOMAIN_COLLISION_CANDIDATE",
    }:
        return "MANUAL CHECK", (
            "A possible duplicate or same-domain product was found; distinct products "
            "cannot be ruled out automatically."
        ), "POSSIBLE_DUPLICATE"

    identity = cached_identity_status or identity_check(name, verification)[0]
    if identity == "MISMATCH":
        return "REJECT", "Official page identity does not match the candidate product name.", "PRODUCT_IDENTITY_MISMATCH"

    evidence = verification.get("aiEvidence") or []
    if not evidence:
        if has_ai_signal(candidate.get("description")):
            return "MANUAL CHECK", (
                "The source description claims AI functionality, but the official page "
                "did not provide specific AI evidence."
            ), "INSUFFICIENT_OFFICIAL_AI_EVIDENCE"
        return "REJECT", (
            "Neither the official page nor the source description provided specific "
            "evidence of AI functionality."
        ), "NO_AI_EVIDENCE"
    if identity != "MATCH":
        return "MANUAL CHECK", "Product identity could not be established from the official page or domain.", "IDENTITY_UNCONFIRMED"
    if cached_description_match is None:
        matched, terms = description_match(candidate.get("description"), verification.get("coreText"))
    else:
        matched = cached_description_match
        terms = matched_description_terms
    if not matched:
        return "MANUAL CHECK", (
            "The official page shows AI-related functionality, but the candidate description "
            "could not be reliably matched to the page."
        ), "DESCRIPTION_UNCONFIRMED"
    return "APPROVE", (
        "Product identity matches the official page; specific AI evidence and product "
        "description terms were found in first-party page content. Evidence terms: "
        + ", ".join(item["term"] for item in evidence)
        + ". Description overlap: " + ", ".join(terms or matched_description_terms[:8]) + "."
    ), "VERIFIED_IDENTITY_AI_AND_DESCRIPTION"


def record_to_csv_value(value: object) -> object:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if value is None:
        return ""
    return value


def validate_outputs(
    output_records: list[dict],
    originals: list[dict],
    protected_hashes: dict[str, str | None],
    csv_path: Path,
) -> None:
    if len(output_records) != len(originals):
        raise ValueError("Final review count does not equal the input candidate count.")
    allowed = {"APPROVE", "MANUAL CHECK", "REJECT"}
    counts = Counter(record.get("decision") for record in output_records)
    if set(counts) - allowed or sum(counts.values()) != len(originals):
        raise ValueError("Every input candidate must have exactly one valid decision.")
    required = {
        "productName", "website", "description", "decision", "reviewReason",
        "verificationStatus", "httpStatus", "pageTitle", "aiEvidence",
        "evidenceUrl", "duplicateStatus", "checkedAt", "sourceProvenance",
    }
    for index, record in enumerate(output_records):
        missing = [field for field in required if field not in record]
        if missing:
            raise ValueError(f"Record {index} is missing required fields: {missing}")
        if record.get("sourceProvenance") != originals[index].get("sourceProvenance"):
            raise ValueError(f"Source provenance changed for input record {index}.")
        for field in ("productName", "website", "description"):
            if record.get(field) != originals[index].get(field):
                raise ValueError(f"Original candidate field {field} changed at record {index}.")
    current_hashes = {str(path): sha256(path) for path in PROTECTED_FILES}
    for path, digest in protected_hashes.items():
        if current_hashes.get(path) != digest:
            raise ValueError(f"Protected input/project file changed: {path}")
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        expected_columns = required | {
            "automatedDecision", "automatedReason", "sourceValidation",
            "duplicateMatches", "identityStatus", "descriptionMatch",
            "matchedDescriptionTerms", "reviewReason", "checkedAt",
        }
        if not expected_columns.issubset(set(reader.fieldnames or [])):
            raise ValueError("Final review CSV is missing required columns.")
        if len(rows) != len(originals):
            raise ValueError("Final review CSV count does not equal input count.")
    if sum(counts.values()) != len(originals):
        raise ValueError("Decision partition total does not equal input count.")


def load_prior_review(candidates: list[dict]) -> list[dict] | None:
    prior_path = OUTPUTS["review_json"]
    if not prior_path.exists():
        return None
    report_path = OUTPUTS["report"]
    if not report_path.exists() or any(not path.exists() for path in OUTPUTS.values()):
        raise FileExistsError("A partial prior output set exists; refusing to overwrite it.")
    report = report_path.read_text(encoding="utf-8")
    if "GraphOne Data Intelligence — 803 Candidate Review" not in report:
        raise FileExistsError("Existing output set is not recognized as a prior run of this reviewer.")
    with prior_path.open(encoding="utf-8") as stream:
        prior = json.load(stream)
    if len(prior) != len(candidates):
        raise ValueError("Prior review count does not match the current input.")
    for index, (old, new) in enumerate(zip(prior, candidates)):
        for field in ("productName", "website", "sourceProvenance"):
            if old.get(field) != new.get(field):
                raise ValueError(f"Prior review does not match current input at record {index} ({field}).")
    return prior


def write_outputs(
    records: list[dict],
    originals: list[dict],
    report: str,
    protected_hashes: dict[str, str | None],
) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    existing = [path for path in OUTPUTS.values() if path.exists()]
    if existing and len(existing) != len(OUTPUTS):
        raise FileExistsError("A partial prior output set exists; refusing to overwrite it.")
    temps = {key: path.with_name(path.name + f".{os.getpid()}.tmp") for key, path in OUTPUTS.items()}
    if any(path.exists() for path in temps.values()):
        raise FileExistsError("A staging file already exists; no output was written.")
    partitions = {
        "approved": [record for record in records if record["decision"] == "APPROVE"],
        "manual": [record for record in records if record["decision"] == "MANUAL CHECK"],
        "rejected": [record for record in records if record["decision"] == "REJECT"],
    }
    original_fields = []
    for record in records:
        for key in record:
            if key not in original_fields:
                original_fields.append(key)
    csv_path = temps["review_csv"]
    committed = []
    backup_dir = None
    try:
        with temps["review_json"].open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(records, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=original_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows({
                key: record_to_csv_value(value) for key, value in record.items()
            } for record in records)
        for key in ("approved", "manual", "rejected"):
            with temps[key].open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(partitions[key], stream, indent=2, ensure_ascii=False)
                stream.write("\n")
        with temps["report"].open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(report)

        with temps["review_json"].open(encoding="utf-8") as stream:
            check = json.load(stream)
        if len(check) != len(records):
            raise ValueError("Staged JSON failed record count validation.")
        for key in ("approved", "manual", "rejected"):
            with temps[key].open(encoding="utf-8") as stream:
                subset = json.load(stream)
            expected = [r for r in records if r["decision"] == {
                "approved": "APPROVE", "manual": "MANUAL CHECK", "rejected": "REJECT"
            }[key]]
            if len(subset) != len(expected):
                raise ValueError(f"Staged {key} JSON failed partition validation.")
        with csv_path.open(encoding="utf-8-sig", newline="") as stream:
            csv_rows = list(csv.DictReader(stream))
        if len(csv_rows) != len(records):
            raise ValueError("Staged CSV failed record count validation.")
        validate_outputs(records, originals, protected_hashes, csv_path)

        if existing:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup_dir = DATA / f"products_803_previous_run_{stamp}"
            backup_dir.mkdir()
            for path in existing:
                shutil.copy2(path, backup_dir / path.name)

        final_keys = ["review_json", "review_csv", "approved", "manual", "rejected", "report"]
        for key in final_keys:
            os.replace(temps[key], OUTPUTS[key])
            committed.append(OUTPUTS[key])
        with OUTPUTS["review_json"].open(encoding="utf-8") as stream:
            final_check = json.load(stream)
        if len(final_check) != len(records):
            raise ValueError("Committed JSON failed final record-count validation.")
        validate_outputs(records, originals, protected_hashes, OUTPUTS["review_csv"])
        for path, digest in protected_hashes.items():
            if sha256(Path(path)) != digest:
                raise ValueError(f"Protected file changed during output commit: {path}")
    except Exception:
        if backup_dir and backup_dir.exists():
            for path in committed:
                backup = backup_dir / path.name
                if backup.exists():
                    shutil.copy2(backup, path)
        else:
            for path in committed:
                if path.exists():
                    path.unlink()
        for path in temps.values():
            if path.exists():
                path.unlink()
        raise


def build_report(records: list[dict], protected_hashes: dict[str, str | None]) -> str:
    counts = Counter(record["decision"] for record in records)
    verification_failures = [
        record for record in records
        if record.get("httpStatus") is None or not 200 <= int(record["httpStatus"]) < 300
        or record.get("verificationStatus") != "HTTP_OK"
    ]
    strong = sum(bool(record.get("strongAiEvidence")) for record in records)
    insufficient = sum(
        not record.get("strongAiEvidence")
        or record.get("identityStatus") != "MATCH"
        or not record.get("descriptionMatch")
        for record in records
    )
    confirmed_duplicates = sum(
        record.get("duplicateStatus") in {"DUPLICATE_EXISTING", "DUPLICATE_CANDIDATE_GROUP"}
        for record in records
    )
    possible_duplicates = sum(
        record.get("duplicateStatus") in {
            "DOMAIN_MATCH_EXISTING", "NAME_MATCH_EXISTING",
            "NAME_COLLISION_CANDIDATE", "DOMAIN_COLLISION_CANDIDATE",
        }
        for record in records
    )
    robots_denied = sum(record.get("verificationStatus") == "ROBOTS_DISALLOWED" for record in records)
    source_invalid = sum(record.get("sourceValidation") != "VALID" for record in records)
    errors = [
        f"- {record.get('productName')}: {record.get('verificationStatus')} — "
        f"{record.get('errorDetail') or record.get('reviewReason')}"
        for record in verification_failures[:30]
    ]
    protected_lines = [
        f"- {Path(path).name}: {'unchanged' if sha256(Path(path)) == digest else 'CHANGED'}"
        for path, digest in protected_hashes.items()
    ]
    output_lines = [f"- {path.name}: {path.resolve()}" for path in OUTPUTS.values()]
    lines = [
        "GraphOne Data Intelligence — 803 Candidate Review",
        f"Generated at: {utc_now()}",
        f"Input: {INPUT.resolve()}",
        "",
        f"Total candidates processed: {len(records)}",
        f"APPROVE: {counts.get('APPROVE', 0)}",
        f"MANUAL CHECK: {counts.get('MANUAL CHECK', 0)}",
        f"REJECT: {counts.get('REJECT', 0)}",
        f"Confirmed duplicate records: {confirmed_duplicates}",
        f"Possible duplicate/domain/name collisions: {possible_duplicates}",
        f"Website verification failures/incomplete checks: {len(verification_failures)}",
        f"Robots-disallowed sites: {robots_denied}",
        f"Records with strong first-party AI evidence: {strong}",
        f"Records without sufficient combined evidence: {insufficient}",
        f"Source provenance validation issues: {source_invalid}",
        f"Outbound HTTP requests in this pass (including robots.txt): {_stats.get('httpRequests', 0)}",
        f"robots.txt requests: {_stats.get('robotsRequests', 0)}",
        f"Official website requests: {_stats.get('websiteRequests', 0)}",
        f"Reused prior verified results: {_stats.get('cacheHits', 0)}",
        f"Redirect-retry website checks: {_stats.get('retryChecks', 0)}",
        "",
        "Protected files",
        *protected_lines,
        "",
        "Outputs",
        *output_lines,
        "",
        "Verification errors (first 30; complete per-record details are in the review JSON):",
        *(errors or ["- None."]),
        "",
        "Limitations",
        "- This is a conservative automated review of public first-party HTML, not human or legal certification.",
        "- Sites that block access, disallow crawling, render only client-side content, or provide ambiguous evidence are routed to MANUAL CHECK.",
        "- APPROVE requires page/domain identity, specific AI evidence in first-party page content, and overlap between the supplied description and visible page text.",
        "- Domain-only or name-only overlap is treated as a possible duplicate and routed to MANUAL CHECK; exact name-and-domain matches are rejected as duplicates.",
        "- HTTP 404/410 responses are rejected; an accessible page does not by itself prove a service is not discontinued, so explicit shutdown notices may still need manual review.",
        "- Source provenance is checked against approved directory domains and product-listing URL formats; directory listing pages were not all re-fetched during this review.",
        "- Product descriptions, source provenance, original source URLs, and original candidate fields are preserved. Original automated decision/reason are retained as automatedDecision/automatedReason.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    if not INPUT.exists():
        raise FileNotFoundError(f"Required candidate dataset not found: {INPUT}")
    protected_hashes = {str(path): sha256(path) for path in PROTECTED_FILES}
    with INPUT.open(encoding="utf-8") as stream:
        source_records = json.load(stream)
    if not isinstance(source_records, list):
        raise ValueError("Input candidate dataset must be a JSON list.")
    candidates = [record for record in source_records if record.get("decision") == "APPROVE"]
    print(f"Input records: {len(source_records)}; APPROVE candidates to review: {len(candidates)}")
    if len(candidates) != EXPECTED_COUNT:
        raise ValueError(f"Expected {EXPECTED_COUNT} APPROVE candidates; found {len(candidates)}.")
    prior_records = load_prior_review(candidates)

    existing_domains, existing_names = load_existing_catalog()
    duplicate_results = candidate_duplicates(candidates, existing_domains, existing_names)
    print(
        "Existing catalog indexes:",
        f"{len(existing_domains)} domains, {len(existing_names)} normalized names;",
        "candidate duplicate scan complete.",
    )

    verifications: list[dict | None] = [None] * len(candidates)
    cached_metrics: list[dict | None] = [None] * len(candidates)
    pending_indices = []
    if prior_records:
        for index, prior in enumerate(prior_records):
            if prior.get("verificationStatus") != "REDIRECT_LOOP":
                verifications[index] = {
                    "checkedAt": prior.get("checkedAt"),
                    "requestedUrl": prior.get("website"),
                    "finalUrl": prior.get("officialFinalUrl"),
                    "verificationStatus": prior.get("verificationStatus", "INCOMPLETE"),
                    "httpStatus": prior.get("httpStatus"),
                    "pageTitle": prior.get("pageTitle", ""),
                    "metaDescription": prior.get("metaDescription", ""),
                    "aiEvidence": prior.get("aiEvidence", []),
                    "strongAiEvidence": bool(prior.get("strongAiEvidence")),
                    "errorDetail": prior.get("errorDetail", ""),
                    "robotsStatus": prior.get("robotsStatus", ""),
                    "redirectedAcrossDomains": False,
                }
                cached_metrics[index] = prior
                _stats["cacheHits"] += 1
            else:
                pending_indices.append(index)
    else:
        pending_indices = list(range(len(candidates)))
    print(
        f"Reusing {len(candidates) - len(pending_indices)} prior verification results; "
        f"retrying {len(pending_indices)} affected website checks."
    )
    _stats["retryChecks"] = len(pending_indices)

    url_groups: dict[str, list[int]] = defaultdict(list)
    for index in pending_indices:
        candidate = candidates[index]
        cache_key = normalize_url(candidate.get("website")) or f"invalid:{index}"
        url_groups[cache_key].append(index)
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {
            executor.submit(fetch_page, candidates[indexes[0]].get("website")): indexes
            for indexes in url_groups.values()
        }
        completed = 0
        for future in as_completed(futures):
            indexes = futures[future]
            try:
                verification = future.result()
            except Exception as error:
                verification = {
                    "checkedAt": utc_now(),
                    "requestedUrl": normalize_url(candidates[indexes[0]].get("website")),
                    "finalUrl": None,
                    "verificationStatus": "FETCH_ERROR",
                    "httpStatus": None,
                    "pageTitle": "",
                    "metaDescription": "",
                    "h1": "",
                    "coreText": "",
                    "aiEvidence": [],
                    "strongAiEvidence": False,
                    "errorDetail": f"Unhandled verification error: {error}",
                    "robotsStatus": "",
                    "redirectedAcrossDomains": False,
                }
            for index in indexes:
                verifications[index] = copy.deepcopy(verification)
            completed += 1
            if completed % 25 == 0 or completed == len(url_groups):
                print(
                    f"Unique website checks completed: {completed}/{len(url_groups)}",
                    f"| HTTP requests: {_stats.get('httpRequests', 0)}",
                )

    reviewed = []
    for index, original in enumerate(candidates):
        verification = verifications[index] or {}
        duplicate = duplicate_results[index]
        source_status, source_reason = validate_source_provenance(original)
        identity, identity_matches = identity_check(original.get("productName"), verification)
        prior = cached_metrics[index]
        if prior is not None:
            identity = prior.get("identityStatus", identity)
            identity_matches = prior.get("identityMatchedTerms", identity_matches)
            description_ok = bool(prior.get("descriptionMatch"))
            description_terms = prior.get("matchedDescriptionTerms", [])
        else:
            description_ok, description_terms = description_match(
                original.get("description"), verification.get("coreText")
            )
        decision, reason, review_status = classify(
            original,
            verification,
            duplicate,
            source_status,
            source_reason,
            description_terms,
            cached_identity_status=identity if prior is not None else None,
            cached_description_match=description_ok if prior is not None else None,
        )
        record = copy.deepcopy(original)
        record["automatedDecision"] = original.get("decision")
        record["automatedReason"] = original.get("reason")
        record["decision"] = decision
        record["reviewReason"] = reason
        record["verificationStatus"] = verification.get("verificationStatus", "INCOMPLETE")
        record["httpStatus"] = verification.get("httpStatus")
        record["pageTitle"] = verification.get("pageTitle", "")
        record["aiEvidence"] = verification.get("aiEvidence", [])
        record["strongAiEvidence"] = bool(verification.get("strongAiEvidence"))
        record["evidenceUrl"] = verification.get("finalUrl") or verification.get("requestedUrl")
        record["duplicateStatus"] = duplicate["status"]
        record["duplicateMatches"] = duplicate["matches"]
        record["checkedAt"] = verification.get("checkedAt") or utc_now()
        record["reviewStatus"] = review_status
        record["sourceValidation"] = source_status
        record["sourceValidationReason"] = source_reason
        record["identityStatus"] = identity
        record["identityMatchedTerms"] = identity_matches
        record["descriptionMatch"] = description_ok
        record["matchedDescriptionTerms"] = description_terms
        record["metaDescription"] = verification.get("metaDescription", "")
        record["officialFinalUrl"] = verification.get("finalUrl")
        record["robotsStatus"] = verification.get("robotsStatus", "")
        record["errorDetail"] = verification.get("errorDetail", "")
        reviewed.append(record)

    counts = Counter(record["decision"] for record in reviewed)
    print("Final decisions:", dict(counts))
    report = build_report(reviewed, protected_hashes)
    write_outputs(reviewed, candidates, report, protected_hashes)
    print(report)


if __name__ == "__main__":
    main()
