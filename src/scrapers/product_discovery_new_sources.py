import csv
import hashlib
import ipaddress
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"

RAW_FILE = DATA_DIR / "products_new_sources_raw.json"
REVIEW_FILE = DATA_DIR / "products_new_sources_review.csv"
CANDIDATES_JSON_FILE = DATA_DIR / "products_new_sources_candidates.json"
CANDIDATES_CSV_FILE = DATA_DIR / "products_new_sources_candidates.csv"

FUTUREPEDIA_SITEMAP = "https://www.futurepedia.io/sitemap_tools.xml"
FUTURETOOLS_SITEMAP = "https://futuretools.io/sitemap.xml"
AIXPLORIA_DIRECTORY = "https://www.aixploria.com/en/ultimate-list-ai/"

TARGET_CANDIDATES = 1000
LISTING_DELAY_SECONDS = 0.25
OFFICIAL_WORKERS = 8
MAX_PAGE_BYTES = 2_000_000
USER_AGENT = "GraphOne-Data-Intelligence/1.0 (public catalog research)"
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

AI_EVIDENCE_PATTERNS = [
    ("artificial intelligence", re.compile(r"\bartificial intelligence\b", re.I)),
    ("machine learning", re.compile(r"\bmachine learning\b", re.I)),
    ("generative AI", re.compile(r"\bgenerative\s+ai\b", re.I)),
    ("large language model", re.compile(r"\blarge language models?\b|\bllms?\b", re.I)),
    ("AI-powered", re.compile(r"\bai[- ]powered\b", re.I)),
    ("AI assistant", re.compile(r"\bai assistant\b", re.I)),
    ("AI agent", re.compile(r"\bai agents?\b", re.I)),
    ("chatbot", re.compile(r"\bchatbots?\b", re.I)),
    ("computer vision", re.compile(r"\bcomputer vision\b", re.I)),
    ("natural language processing", re.compile(r"\bnatural language processing\b", re.I)),
    ("image generation", re.compile(r"\bimage generation\b|\btext[- ]to[- ]image\b", re.I)),
    ("video generation", re.compile(r"\bvideo generation\b|\btext[- ]to[- ]video\b", re.I)),
    ("speech recognition", re.compile(r"\bspeech recognition\b|\bvoice transcription\b", re.I)),
    ("AI", re.compile(r"\bAI\b", re.I)),
]

AIXPLORIA_NON_PRODUCT_SLUGS = {
    "ultimate-list-ai",
    "categories-ai",
    "tutorials-video-ai-free-lessons",
    "last-ai",
    "free-ai",
    "ai-news-today",
    "bonus-extras-ai",
    "add-ai",
    "aixploria-newsletter",
    "verified-ai-tools",
    "ai-freemium",
    "ai-paid",
    "ai-free-trial",
    "disclosure",
    "about",
    "contact",
}

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xml,application/json;q=0.9,*/*;q=0.8",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def validate_public_url(url):
    parsed = urlsplit(str(url or "").strip())
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Not an absolute HTTP(S) URL: {url!r}")

    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError(f"Local host URL is not allowed: {url!r}")

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError(f"Non-public IP URL is not allowed: {url!r}")


def get_response(url, timeout=(5, 20), max_redirects=5):
    current_url = url
    for _ in range(max_redirects + 1):
        validate_public_url(current_url)
        response = requests.get(
            current_url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=False,
            stream=True,
        )
        if response.status_code not in (301, 302, 303, 307, 308):
            return response, current_url

        location = response.headers.get("Location")
        response.close()
        if not location:
            raise requests.RequestException(f"Redirect without Location: {current_url}")
        current_url = urljoin(current_url, location)

    raise requests.TooManyRedirects(f"Too many redirects for {url}")


def read_response_body(response, max_bytes=MAX_PAGE_BYTES):
    chunks = []
    size = 0
    for chunk in response.iter_content(chunk_size=16384):
        if not chunk:
            continue
        remaining = max_bytes - size
        chunks.append(chunk[:remaining])
        size += min(len(chunk), remaining)
        if size >= max_bytes:
            break
    encoding = response.encoding or "utf-8"
    return b"".join(chunks).decode(encoding, errors="replace")


def normalize_url(value):
    if not value:
        return None
    value = unescape(str(value)).strip()
    if value.startswith("//"):
        value = "https:" + value
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() not in ("http", "https") or not hostname:
        return None

    host = hostname.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    netloc = host
    if port and port not in (80, 443):
        netloc = f"{host}:{port}"

    query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"ref", "fpr", "affiliate", "aff"}
    ]
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), netloc, path, urlencode(query), ""))


def domain_for(url):
    normalized = normalize_url(url)
    if not normalized:
        return ""
    return (urlsplit(normalized).hostname or "").lower().removeprefix("www.")


def normalized_name(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def parse_sitemap(url):
    response, final_url = get_response(url, timeout=(5, 30))
    try:
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
    finally:
        response.close()

    if root.tag.endswith("sitemapindex"):
        return [
            node.text.strip()
            for node in root.findall(".//sm:sitemap/sm:loc", SITEMAP_NS)
            if node.text and node.text.strip()
        ]
    if root.tag.endswith("urlset"):
        return [
            node.text.strip()
            for node in root.findall(".//sm:url/sm:loc", SITEMAP_NS)
            if node.text and node.text.strip()
        ]
    raise ValueError(f"Unexpected sitemap format at {final_url}")


def unique_urls(urls):
    result = []
    seen = set()
    for value in urls:
        normalized = normalize_url(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def discover_futurepedia_urls():
    urls = unique_urls(parse_sitemap(FUTUREPEDIA_SITEMAP))
    return [url for url in urls if "/tool/" in urlsplit(url).path]


def discover_futuretools_urls():
    child_sitemaps = parse_sitemap(FUTURETOOLS_SITEMAP)
    tool_sitemaps = [
        url for url in child_sitemaps
        if re.search(r"/tools-\d+\.xml$", urlsplit(url).path)
    ]
    urls = []
    for sitemap_url in tool_sitemaps:
        urls.extend(parse_sitemap(sitemap_url))
    return [
        url for url in unique_urls(urls)
        if "/tools/" in urlsplit(url).path
    ]


def discover_aixploria_urls():
    response, final_url = get_response(AIXPLORIA_DIRECTORY)
    try:
        response.raise_for_status()
        html = read_response_body(response, max_bytes=5_000_000)
    finally:
        response.close()

    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(final_url, anchor["href"].strip())
        normalized = normalize_url(href)
        if not normalized:
            continue
        parsed = urlsplit(normalized)
        if parsed.hostname not in {"aixploria.com", "www.aixploria.com"}:
            continue
        match = re.fullmatch(r"/en/([a-z0-9][a-z0-9-]*)/?", parsed.path, re.I)
        if not match or match.group(1).lower() in AIXPLORIA_NON_PRODUCT_SLUGS:
            continue
        if anchor.get_text(" ", strip=True):
            urls.append(normalized)
    return unique_urls(urls)


def flatten_jsonld(value):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from flatten_jsonld(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from flatten_jsonld(nested)


def jsonld_products(soup):
    products = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        try:
            parsed = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for item in flatten_jsonld(parsed):
            types = item.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if any(str(value).lower() in {"softwareapplication", "product", "webapplication"} for value in types):
                if item.get("name"):
                    products.append(item)
    return products


def meta_content(soup, *keys):
    for key in keys:
        for attribute in ("name", "property"):
            tag = soup.find("meta", attrs={attribute: key})
            if tag and tag.get("content"):
                return tag["content"].strip()
    return ""


def extract_official_url(soup, page_url, product_data, source_name):
    source_host = domain_for(page_url)
    label_patterns = re.compile(r"^(visit(\s+website)?|official\s+website|website|visit\s+site)$", re.I)
    possible = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(page_url, anchor["href"].strip())
        normalized = normalize_url(href)
        if not normalized:
            continue
        host = domain_for(normalized)
        if not host or host == source_host:
            continue
        if any(social in host for social in (
            "facebook.com", "linkedin.com", "instagram.com", "youtube.com",
            "tiktok.com", "twitter.com", "x.com", "telegram.me", "wikipedia.org"
        )):
            continue
        text = anchor.get_text(" ", strip=True)
        if label_patterns.fullmatch(text):
            possible.insert(0, normalized)
        else:
            possible.append(normalized)

    structured_url = normalize_url(product_data.get("url"))
    if structured_url and domain_for(structured_url) != source_host:
        return structured_url
    return possible[0] if possible else None


def extract_listing(source_name, page_url, seed_name=None):
    collected_at = utc_now()
    raw = {
        "sourceName": source_name,
        "sourceListingUrl": page_url,
        "collectedAt": collected_at,
    }
    try:
        response, final_url = get_response(page_url)
        try:
            status = response.status_code
            html = read_response_body(response)
        finally:
            response.close()
    except (requests.RequestException, ValueError) as error:
        raw.update({"fetchStatus": "ERROR", "fetchError": str(error)})
        return raw, None, status_is_blocking(error)

    raw.update({"fetchStatus": status, "finalListingUrl": final_url})
    if status in (403, 429):
        raw["fetchError"] = f"Source returned HTTP {status}; source paused."
        return raw, None, True
    if status < 200 or status >= 300:
        raw["fetchError"] = f"Source returned HTTP {status}."
        return raw, None, False

    soup = BeautifulSoup(html, "html.parser")
    apps = jsonld_products(soup)
    product_data = apps[0] if apps else {}
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description = (
        str(product_data.get("description") or "")
        or meta_content(soup, "description", "og:description")
    )
    name = str(product_data.get("name") or seed_name or "").strip()
    if not name and title:
        name = re.split(r"\s+[|–—-]\s+", title, maxsplit=1)[0].strip()

    category = product_data.get("applicationCategory") or product_data.get("category")
    offer = product_data.get("offers")
    pricing = None
    if isinstance(offer, dict):
        pricing = offer.get("price")
    elif isinstance(offer, list) and offer:
        pricing = offer[0].get("price") if isinstance(offer[0], dict) else None

    official_url = extract_official_url(soup, final_url, product_data, source_name)
    raw.update({
        "pageTitle": title,
        "structuredDataType": product_data.get("@type"),
        "productName": name,
        "description": description,
        "category": category,
        "pricing": pricing,
        "officialWebsiteRaw": official_url,
    })

    if not name:
        return raw, None, False
    if source_name == "Aixploria" and not product_data:
        return raw, None, False

    candidate_data = {
        "productName": name,
        "website": normalize_url(official_url),
        "description": description or None,
        "category": category,
        "pricing": pricing,
    }
    raw_id = hashlib.sha256(f"{source_name}\n{page_url}".encode("utf-8")).hexdigest()
    candidate_data["rawRecordId"] = raw_id
    candidate_data["sourceProvenance"] = [{
        "sourceName": source_name,
        "sourceListingUrl": page_url,
        "collectedAt": collected_at,
    }]
    candidate_data["collectedAt"] = collected_at
    return raw, candidate_data, False


def status_is_blocking(error):
    response = getattr(error, "response", None)
    return bool(response is not None and response.status_code in (403, 429))


def load_existing_products():
    paths = [
        DATA_DIR / "products.json",
        DATA_DIR / "products_merged_review.json",
        DATA_DIR / "products_scraped.json",
        DATA_DIR / "mydentify_approved_products.json",
    ]
    domains = set()
    names = set()
    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            records = json.load(f)
        if not isinstance(records, list):
            raise ValueError(f"Expected a JSON list in {path}")
        for record in records:
            content = record.get("content") or {}
            name = record.get("productName") or content.get("productName") or record.get("name")
            if name:
                names.add(normalized_name(name))
            website = (
                record.get("website")
                or record.get("url")
                or content.get("website")
            )
            domain = domain_for(website)
            if domain:
                domains.add(domain)
    return domains, names


def candidate_key(candidate):
    domain = domain_for(candidate.get("website"))
    if domain:
        return "domain:" + domain
    return "name:" + normalized_name(candidate.get("productName"))


def merge_candidate(target, incoming):
    known = {
        (item["sourceName"], item["sourceListingUrl"])
        for item in target["sourceProvenance"]
    }
    for item in incoming["sourceProvenance"]:
        key = (item["sourceName"], item["sourceListingUrl"])
        if key not in known:
            target["sourceProvenance"].append(item)
            known.add(key)
    if not target.get("description") and incoming.get("description"):
        target["description"] = incoming["description"]
    if not target.get("category") and incoming.get("category"):
        target["category"] = incoming["category"]
    if not target.get("pricing") and incoming.get("pricing"):
        target["pricing"] = incoming["pricing"]


def fetch_official_page(candidate):
    url = candidate.get("website")
    checked_at = utc_now()
    if not url:
        return {
            "checkedAt": checked_at,
            "status": "MISSING_URL",
            "requestedUrl": None,
            "finalUrl": None,
            "httpStatus": None,
            "pageTitle": "",
            "metaDescription": "",
            "aiEvidenceTerms": [],
        }

    try:
        response, final_url = get_response(url, timeout=(5, 12))
        try:
            status = response.status_code
            html = read_response_body(response, max_bytes=MAX_PAGE_BYTES)
        finally:
            response.close()
    except (requests.RequestException, ValueError) as error:
        return {
            "checkedAt": checked_at,
            "status": "ERROR",
            "requestedUrl": url,
            "finalUrl": None,
            "httpStatus": None,
            "pageTitle": "",
            "metaDescription": "",
            "aiEvidenceTerms": [],
            "error": str(error),
        }

    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description = meta_content(soup, "description", "og:description")
    visible_text = " ".join(soup.stripped_strings)
    evidence_text = f"{title} {description} {visible_text[:50000]}"
    evidence = [
        label for label, pattern in AI_EVIDENCE_PATTERNS
        if label != "AI" and pattern.search(evidence_text)
    ]
    if AI_EVIDENCE_PATTERNS[-1][1].search(f"{title} {description}"):
        evidence.append("AI")

    return {
        "checkedAt": checked_at,
        "status": "HTTP",
        "requestedUrl": url,
        "finalUrl": normalize_url(final_url),
        "httpStatus": status,
        "pageTitle": title,
        "metaDescription": description,
        "aiEvidenceTerms": evidence,
    }


def classify(candidate, verification):
    status = verification.get("httpStatus")
    evidence = verification.get("aiEvidenceTerms") or []
    if status in (404, 410):
        return "REJECT", f"Official website returned HTTP {status}."
    if status is not None and 200 <= status < 300 and evidence:
        return "APPROVE", (
            "Official website responded successfully and contains AI evidence: "
            + ", ".join(evidence)
            + "."
        )
    if verification.get("status") == "MISSING_URL":
        return "MANUAL CHECK", "No official website URL was present in the source listing."
    if verification.get("status") == "ERROR":
        return "MANUAL CHECK", "Official website could not be verified: " + verification.get("error", "")
    if status is not None and 200 <= status < 300:
        listing_text = " ".join(
            str(candidate.get(field) or "")
            for field in ("productName", "description")
        )
        listing_evidence = [
            label for label, pattern in AI_EVIDENCE_PATTERNS
            if pattern.search(listing_text)
        ]
        if listing_evidence:
            return "MANUAL CHECK", (
                "The listing suggests AI functionality, but the official page "
                "did not confirm it."
            )
        return "REJECT", (
            "Neither the listing description nor the reachable official page "
            "substantiated AI functionality."
        )
    return "MANUAL CHECK", f"Official website returned HTTP {status}; manual verification is needed."


def source_page_queues():
    futurepedia = discover_futurepedia_urls()
    futuretools = discover_futuretools_urls()
    aixploria = discover_aixploria_urls()
    stats = {
        "Futurepedia": len(futurepedia),
        "FutureTools": len(futuretools),
        "Aixploria": len(aixploria),
    }
    queues = {
        "Futurepedia": [(url, None) for url in futurepedia],
        "FutureTools": [(url, None) for url in futuretools],
        "Aixploria": [(url, None) for url in aixploria],
    }
    return queues, stats


def csv_candidate_row(candidate):
    verification = candidate["officialVerification"]
    provenance = candidate["sourceProvenance"]
    return {
        "productName": candidate["productName"],
        "website": candidate.get("website") or "",
        "normalizedDomain": domain_for(candidate.get("website")),
        "description": candidate.get("description") or "",
        "category": json.dumps(candidate.get("category"), ensure_ascii=False) if isinstance(candidate.get("category"), (dict, list)) else (candidate.get("category") or ""),
        "pricing": candidate.get("pricing") or "",
        "sourceNames": "; ".join(dict.fromkeys(x["sourceName"] for x in provenance)),
        "sourceListingUrls": "; ".join(x["sourceListingUrl"] for x in provenance),
        "collectedAt": candidate["collectedAt"],
        "officialCheckStatus": verification.get("status"),
        "officialHttpStatus": verification.get("httpStatus"),
        "officialFinalUrl": verification.get("finalUrl") or "",
        "officialPageTitle": verification.get("pageTitle") or "",
        "officialMetaDescription": verification.get("metaDescription") or "",
        "aiEvidenceTerms": "; ".join(verification.get("aiEvidenceTerms") or []),
        "decision": candidate["decision"],
        "reason": candidate["reason"],
    }


def write_and_validate(raw_records, candidates, review_rows):
    outputs = [RAW_FILE, REVIEW_FILE, CANDIDATES_JSON_FILE, CANDIDATES_CSV_FILE]
    for path in outputs:
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite existing output: {path}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    temps = [path.with_name(path.name + f".{stamp}.tmp") for path in outputs]
    for path in temps:
        if path.exists():
            raise FileExistsError(f"Temporary output already exists: {path}")

    candidate_fields = list(csv_candidate_row(candidates[0]).keys()) if candidates else [
        "productName", "website", "normalizedDomain", "description", "category",
        "pricing", "sourceNames", "sourceListingUrls", "collectedAt",
        "officialCheckStatus", "officialHttpStatus", "officialFinalUrl",
        "officialPageTitle", "officialMetaDescription", "aiEvidenceTerms",
        "decision", "reason",
    ]
    review_fields = [
        "productName", "website", "sourceNames", "sourceListingUrls",
        "collectedAt", "officialCheckedAt", "officialCheckStatus",
        "officialHttpStatus", "officialFinalUrl", "officialPageTitle",
        "officialMetaDescription", "aiEvidenceTerms", "decision", "reason",
    ]

    try:
        with temps[0].open("w", encoding="utf-8") as f:
            json.dump(raw_records, f, indent=2, ensure_ascii=False)
            f.write("\n")
        with temps[1].open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=review_fields)
            writer.writeheader()
            writer.writerows(review_rows)
        with temps[2].open("w", encoding="utf-8") as f:
            json.dump(candidates, f, indent=2, ensure_ascii=False)
            f.write("\n")
        with temps[3].open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=candidate_fields)
            writer.writeheader()
            writer.writerows(csv_candidate_row(candidate) for candidate in candidates)

        with temps[0].open(encoding="utf-8") as f:
            raw_check = json.load(f)
        with temps[2].open(encoding="utf-8") as f:
            candidate_check = json.load(f)
        with temps[1].open(encoding="utf-8-sig", newline="") as f:
            review_check = list(csv.DictReader(f))
        with temps[3].open(encoding="utf-8-sig", newline="") as f:
            candidate_csv_check = list(csv.DictReader(f))

        if len(raw_check) != len(raw_records):
            raise ValueError("Raw JSON temporary file failed record-count validation.")
        if len(candidate_check) != len(candidates) or len(review_check) != len(candidates):
            raise ValueError("Candidate JSON/review CSV temporary record counts do not match.")
        if len(candidate_csv_check) != len(candidates):
            raise ValueError("Candidate CSV temporary record count does not match.")
        names = [item["productName"] for item in candidate_check]
        if any(not name for name in names):
            raise ValueError("Candidate names are missing.")
        domains = [domain_for(item.get("website")) for item in candidate_check if item.get("website")]
        if len(domains) != len(set(domains)):
            raise ValueError("Candidate website domains are duplicated.")
        if any(item.get("decision") not in {"APPROVE", "MANUAL CHECK", "REJECT"} for item in candidate_check):
            raise ValueError("Candidate file contains an unsupported decision.")

        replaced = []
        try:
            for temp, final in zip(temps, outputs):
                os.replace(temp, final)
                replaced.append(final)
        except Exception:
            for final in replaced:
                final.unlink()
            raise
    except Exception:
        for temp in temps:
            if temp.exists():
                temp.unlink()
        raise


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_paths = [RAW_FILE, REVIEW_FILE, CANDIDATES_JSON_FILE, CANDIDATES_CSV_FILE]
    existing_outputs = [str(path) for path in output_paths if path.exists()]
    if existing_outputs:
        raise SystemExit("STOP: Outputs already exist; no crawl started: " + ", ".join(existing_outputs))

    existing_domains, existing_names = load_existing_products()
    queues, source_stats = source_page_queues()
    print("Public listing URLs discovered:", source_stats)
    print("Existing domains loaded for deduplication:", len(existing_domains))
    print("Target unique new candidates:", TARGET_CANDIDATES)

    source_order = ["Futurepedia", "FutureTools", "Aixploria"]
    positions = {source: 0 for source in source_order}
    blocked = set()
    raw_records = []
    candidates_by_key = {}
    skipped_existing = 0
    request_errors = 0

    while len(candidates_by_key) < TARGET_CANDIDATES:
        progressed = False
        for source_name in source_order:
            if source_name in blocked:
                continue
            queue = queues[source_name]
            index = positions[source_name]
            if index >= len(queue):
                continue
            progressed = True
            page_url, seed_name = queue[index]
            positions[source_name] += 1
            raw, candidate, stop_source = extract_listing(source_name, page_url, seed_name)
            raw_records.append(raw)
            if raw.get("fetchStatus") == "ERROR" or "fetchError" in raw:
                request_errors += 1
                print("Listing issue:", source_name, page_url, raw.get("fetchError"))
            if stop_source:
                blocked.add(source_name)
                print("Pausing source after access/rate-limit response:", source_name)
            if candidate:
                domain = domain_for(candidate.get("website"))
                name_key = normalized_name(candidate.get("productName"))
                if (domain and domain in existing_domains) or (name_key and name_key in existing_names):
                    skipped_existing += 1
                else:
                    key = candidate_key(candidate)
                    if key in candidates_by_key:
                        merge_candidate(candidates_by_key[key], candidate)
                    else:
                        candidates_by_key[key] = candidate
            time.sleep(LISTING_DELAY_SECONDS)
        if not progressed:
            break
        print(
            "Listing pages processed:", len(raw_records),
            "| unique candidates:", len(candidates_by_key),
            "| existing duplicates skipped:", skipped_existing,
        )

    candidates = list(candidates_by_key.values())
    print("Beginning official-site checks:", len(candidates))
    with ThreadPoolExecutor(max_workers=OFFICIAL_WORKERS) as executor:
        futures = {
            executor.submit(fetch_official_page, candidate): index
            for index, candidate in enumerate(candidates)
        }
        checked = 0
        for future in as_completed(futures):
            index = futures[future]
            verification = future.result()
            candidate = candidates[index]
            candidate["officialVerification"] = verification
            candidate["decision"], candidate["reason"] = classify(candidate, verification)
            checked += 1
            if checked % 100 == 0 or checked == len(candidates):
                print("Official sites checked:", checked, "/", len(candidates))

    review_rows = []
    for candidate in candidates:
        verification = candidate["officialVerification"]
        provenance = candidate["sourceProvenance"]
        review_rows.append({
            "productName": candidate["productName"],
            "website": candidate.get("website") or "",
            "sourceNames": "; ".join(dict.fromkeys(x["sourceName"] for x in provenance)),
            "sourceListingUrls": "; ".join(x["sourceListingUrl"] for x in provenance),
            "collectedAt": candidate["collectedAt"],
            "officialCheckedAt": verification.get("checkedAt"),
            "officialCheckStatus": verification.get("status"),
            "officialHttpStatus": verification.get("httpStatus"),
            "officialFinalUrl": verification.get("finalUrl") or "",
            "officialPageTitle": verification.get("pageTitle") or "",
            "officialMetaDescription": verification.get("metaDescription") or "",
            "aiEvidenceTerms": "; ".join(verification.get("aiEvidenceTerms") or []),
            "decision": candidate["decision"],
            "reason": candidate["reason"],
        })

    write_and_validate(raw_records, candidates, review_rows)
    decisions = {
        label: sum(candidate["decision"] == label for candidate in candidates)
        for label in ("APPROVE", "MANUAL CHECK", "REJECT")
    }
    print("\nCollection complete.")
    print("Raw listing records:", len(raw_records))
    print("Unique new candidates:", len(candidates))
    print("Decision counts:", decisions)
    print("Listing request issues:", request_errors)
    print("Candidates skipped as already known:", skipped_existing)
    print("URL nulls requiring manual check:", sum(not item.get("website") for item in candidates))
    print("Source pages processed:", positions)
    print("Created:", RAW_FILE)
    print("Created:", REVIEW_FILE)
    print("Created:", CANDIDATES_JSON_FILE)
    print("Created:", CANDIDATES_CSV_FILE)
    if len(candidates) < TARGET_CANDIDATES:
        print(f"NOTICE: Sources yielded {len(candidates)} candidates, below the {TARGET_CANDIDATES} target.")


if __name__ == "__main__":
    main()
