from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SCRAPERS = ROOT / "src" / "scrapers"
sys.path.insert(0, str(SCRAPERS))

import review_products_803 as reviewer
import product_discovery_new_sources as discovery


TARGET = 1000
WORKERS = 8
BATCH_SIZE = 80
OUTPUTS = {
    "verified_json": DATA / "products_1000_verified.json",
    "verified_csv": DATA / "products_1000_verified.csv",
    "evidence_json": DATA / "products_1000_verification_evidence.json",
    "manual_json": DATA / "products_1000_manual_check.json",
    "rejected_json": DATA / "products_1000_rejected.json",
    "duplicates_csv": DATA / "products_1000_duplicate_log.csv",
    "report": DATA / "products_1000_completion_report.txt",
}

BASELINE = DATA / "products_combined_745.json"
BASELINE_EVIDENCE = DATA / "products_combined_745_evidence.json"
PRIOR_APPROVED = DATA / "products_803_approved.json"
PRIOR_REVIEW = DATA / "products_803_final_review.json"
PRIOR_MANUAL = DATA / "products_803_manual_check.json"
INITIAL_CANDIDATES = DATA / "products_new_sources_candidates.json"
MERGE_REVIEW = DATA / "products_merge_review.json"
SCRAPED = DATA / "products_scraped.json"
MYDENTIFY = DATA / "mydentify_approved_products.json"
IG_RAW = DATA / "ignlab_raw.json"
IG_CANDIDATES = DATA / "ignlab_new_candidates.json"
IG_OFFLINE = DATA / "ignlab_offline_review.json"
NEW_SOURCE_RAW = DATA / "products_new_sources_raw.json"

AI_CONTEXT = re.compile(
    r"\b(?:AI|artificial intelligence|machine learning|deep learning|"
    r"large language models?|LLMs?|generative AI|computer vision|NLP)\b",
    re.I,
)
AI_ACTION = re.compile(
    r"\b(?:generat\w*|creat\w*|writ\w*|compos\w*|edit\w*|analy[sz]\w*|"
    r"summariz\w*|summaris\w*|transcrib\w*|predict\w*|classif\w*|detect\w*|"
    r"recogniz\w*|recognis\w*|recommend\w*|translat\w*|automat\w*|answer\w*|"
    r"search\w*|match\w*|book\w*|schedul\w*|extract\w*|synthesi[sz]\w*|"
    r"design\w*|code\w*|forecast\w*|personaliz\w*|personalise\w*|"
    r"optimiz\w*|optimis\w*|reason\w*|plan\w*|classif\w*|"
    r"text[- ]to[- ](?:image|video|speech)|speech[- ]to[- ]text)\b",
    re.I,
)
AVAILABLE_ACTION = re.compile(
    r"\b(?:get started|start free|try (?:it|now|for free)|sign up|sign in|"
    r"create an account|download|install|pricing|request a demo|book a demo|"
    r"contact sales|open app|launch app|available on|api docs|documentation|"
    r"add to chrome|app store|google play|join beta)\b",
    re.I,
)
INFRASTRUCTURE_ONLY = re.compile(
    r"\b(?:LLM|AI) (?:API )?gateway\b|\bmodel routing\b|\bmodel hosting\b|"
    r"\bAPI gateway (?:for|to) (?:AI|LLM|agents?)\b|"
    r"\bAI infrastructure\b|\bGPU (?:cloud|hosting|compute)\b|"
    r"\binference API\b|\bfoundation model provider\b|\bmodel router\b|"
    r"\bAI developer infrastructure\b|\bvector database\b|"
    r"\bweb access infrastructure for AI\b|\bMCP gateway\b|"
    r"\b(?:REST|MCP|email|web scraping) API for AI agents\b|"
    r"\b(?:connects?|integrates?) .{0,80} to AI (?:agents|tools|assistants)\b|"
    r"\b(?:data|email|social media) API for (?:AI )?agents\b",
    re.I,
)
NON_AI_DIRECTORY = re.compile(
    r"\b(?:AI tools? directory|directory of (?:AI|agent|coding|vibe)|"
    r"directory and review site|independent directory|free directory of|"
    r"catalog of agent skills|curated catalog of agent skills|"
    r"pricing reference|rate card for AI APIs|"
    r"library of AI agent use cases|guide to openduet|"
    r"machine-readable catalog of .* for AI agents|"
    r"machine-readable directory|AI products register themselves|"
    r"AI-related cost calculators|lists? \d[\d,]* tools across|"
    r"free editorial research and comparison platform|"
    r"source-linked knowledge base of .* funding)\b",
    re.I,
)
DISCONTINUED = re.compile(
    r"\b(?:discontinued|shutting down|shut down|service has ended|"
    r"no longer available|product is no longer available|"
    r"end of service|we have closed|sunsetted)\b",
    re.I,
)
SUPPORTED_PRICING = {"FREE", "FREEMIUM", "PAID"}
TRANSIENT_HTTP = {429, 500, 502, 503, 504}
RUN_STARTED = datetime.now(timezone.utc).isoformat()
COUNTERS = Counter()
EVIDENCE: list[dict] = []
MANUAL: list[dict] = []
REJECTED: list[dict] = []
DUPLICATE_LOG: list[dict] = []
VERIFIED: list[dict] = []
VERIFIED_EVIDENCE: list[dict] = []
INDEX: dict[str, dict] = {
    "by_identity": {},
    "by_name": {},
    "by_domain": {},
    "by_url": {},
}


def read_json(path: Path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def data_input_hashes() -> dict[str, str]:
    result = {}
    output_paths = {path.resolve() for path in OUTPUTS.values()}
    for path in DATA.iterdir():
        if not path.is_file() or path.resolve() in output_paths:
            continue
        if re.search(r"product|ignlab|mydentify", path.name, re.I):
            result[str(path.resolve())] = digest(path)
    return result


def normalize_name(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = reviewer.clean_product_name(text)
    return "".join(char for char in text if unicodedata.category(char)[0] in {"L", "N"})


def normalized_domain(value: object) -> str:
    return reviewer.host_for(reviewer.normalize_url(value))


def stable_id(name: str, website: str) -> str:
    identity = f"{normalize_name(name)}|{reviewer.normalize_url(website) or str(website).strip()}"
    return "prod_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def accepted_pricing(value: object):
    if isinstance(value, str) and value.strip().upper() in SUPPORTED_PRICING:
        return value.strip().upper()
    return None


def candidate_from_standard(record: dict, dataset: str, source_listing_url: str | None = None) -> dict:
    content = record.get("content") or {}
    source = record.get("source") or {}
    provenance = record.get("sourceProvenance")
    if isinstance(provenance, dict):
        provenance = [provenance]
    if not isinstance(provenance, list):
        provenance = []
    if not provenance and (source.get("name") or source.get("url")):
        provenance = [{
            "sourceName": source.get("name"),
            "sourceListingUrl": source_listing_url or source.get("url"),
            "collectedAt": record.get("collectedAt"),
        }]
    first_source = provenance[0] if provenance else {}
    return {
        "productName": content.get("productName") or "",
        "website": content.get("website") or "",
        "description": content.get("description") or "",
        "category": content.get("category"),
        "pricingModel": accepted_pricing(content.get("pricingModel")),
        "startupName": content.get("startupName"),
        "sourceName": first_source.get("sourceName") or source.get("name") or "",
        "sourceListingUrl": source_listing_url or first_source.get("sourceListingUrl") or source.get("url"),
        "sourceProvenance": provenance,
        "collectedAt": record.get("collectedAt"),
        "originalSource": source,
        "originalRecord": record,
        "pool": dataset,
    }


def candidate_from_listing(record: dict, pool: str) -> dict:
    provenance = record.get("sourceProvenance") or []
    first_source = provenance[0] if provenance else {}
    return {
        "productName": record.get("productName") or "",
        "website": record.get("website") or "",
        "description": record.get("description") or "",
        "category": record.get("category"),
        "pricingModel": accepted_pricing(record.get("pricing")),
        "startupName": record.get("startupName"),
        "sourceName": first_source.get("sourceName") or record.get("sourceName") or "",
        "sourceListingUrl": first_source.get("sourceListingUrl") or record.get("sourceListingUrl"),
        "sourceProvenance": provenance,
        "collectedAt": record.get("collectedAt"),
        "originalSource": None,
        "originalRecord": record,
        "pool": pool,
    }


def identity_key(candidate: dict) -> tuple[str, str]:
    return normalize_name(candidate.get("productName")), normalized_domain(candidate.get("website"))


def specific_ai_evidence(text: object) -> list[dict]:
    value = re.sub(r"\s+", " ", str(text or ""))
    evidence = []
    for action in AI_ACTION.finditer(value):
        start = max(0, action.start() - 180)
        end = min(len(value), action.end() + 180)
        window = value[start:end]
        if AI_CONTEXT.search(window):
            evidence.append({
                "term": "AI functionality",
                "section": "visible first-party page text",
                "snippet": window[:500].strip(),
                "strength": "strong",
            })
            if len(evidence) >= 5:
                break
    return evidence


def availability_evidence(text: object) -> str:
    value = re.sub(r"\s+", " ", str(text or ""))
    match = AVAILABLE_ACTION.search(value)
    if not match:
        return ""
    start = max(0, match.start() - 70)
    end = min(len(value), match.end() + 120)
    return value[start:end].strip()[:300]


def verify_with_retries(website: str) -> dict:
    last = {}
    for attempt in range(3):
        result = reviewer.fetch_page(website)
        last = result
        status = result.get("httpStatus")
        state = result.get("verificationStatus")
        retryable = (
            status in TRANSIENT_HTTP
            or state in {"FETCH_ERROR", "REDIRECT_WITHOUT_LOCATION"}
        )
        if not retryable or attempt == 2:
            return result
        time.sleep(2 ** attempt)
        COUNTERS["transientRetries"] += 1
    return last


def content_record(candidate: dict) -> dict:
    name = reviewer.clean_product_name(candidate.get("productName"))
    website = reviewer.normalize_url(candidate.get("website")) or str(candidate.get("website") or "").strip()
    provenance = candidate.get("sourceProvenance") or []
    source_name = candidate.get("sourceName") or ""
    source_url = candidate.get("sourceListingUrl")
    source = candidate.get("originalSource")
    if not isinstance(source, dict) or not source:
        source = {"name": source_name or None, "url": source_url or None}
    else:
        source = {"name": source.get("name"), "url": source.get("url")}
    if not source.get("name") and provenance:
        source["name"] = provenance[0].get("sourceName")
    if not source.get("url") and provenance:
        source["url"] = provenance[0].get("sourceListingUrl")

    collected_at = candidate.get("collectedAt") or RUN_STARTED
    return {
        "schemaVersion": "1.0",
        "recordType": "PRODUCT",
        "source": source,
        "content": {
            "productName": name,
            "startupName": candidate.get("startupName"),
            "website": website,
            "description": str(candidate.get("description") or "").strip(),
            "category": candidate.get("category"),
            "pricingModel": accepted_pricing(candidate.get("pricingModel")),
        },
        "collectedAt": collected_at,
        "recordId": stable_id(name, website),
    }


def minimal_verification(result: dict, specific_evidence: list[dict], availability: str) -> dict:
    return {
        "checkedAt": result.get("checkedAt"),
        "requestedUrl": result.get("requestedUrl"),
        "officialProductPageUrl": result.get("finalUrl") or result.get("requestedUrl"),
        "verificationStatus": result.get("verificationStatus"),
        "httpStatus": result.get("httpStatus"),
        "robotsStatus": result.get("robotsStatus"),
        "pageTitle": result.get("pageTitle") or "",
        "metaDescription": result.get("metaDescription") or "",
        "aiEvidence": specific_evidence,
        "availabilityEvidence": availability,
        "errorDetail": result.get("errorDetail") or "",
    }


def make_evidence(candidate: dict, decision: str, reason: str, result: dict, extras: dict | None = None) -> dict:
    product = content_record(candidate)
    specific = specific_ai_evidence(result.get("coreText"))
    availability = availability_evidence(result.get("coreText"))
    ver = minimal_verification(result, specific, availability)
    item = {
        "recordId": product["recordId"],
        "productName": product["content"]["productName"],
        "website": product["content"]["website"],
        "description": product["content"]["description"],
        "sourceName": candidate.get("sourceName"),
        "sourceListingUrl": candidate.get("sourceListingUrl"),
        "sourceProvenance": candidate.get("sourceProvenance") or [],
        "sourceRecordTimestamp": candidate.get("sourceRecordTimestamp"),
        "sourceRecordTimestampType": candidate.get("sourceRecordTimestampType"),
        "collectedAt": product["collectedAt"],
        "verificationTimestamp": ver["checkedAt"],
        "verificationDecision": decision,
        "reviewReason": reason,
        "identityStatus": None,
        "descriptionMatch": False,
        "duplicateStatus": "UNIQUE",
        "verification": ver,
        "sourcePool": candidate.get("pool"),
    }
    if extras:
        item.update(extras)
    return item


def append_partition(product: dict, decision: str, reason: str):
    result = dict(product)
    result["verificationDecision"] = decision
    result["reviewReason"] = reason
    if decision == "MANUAL_CHECK":
        MANUAL.append(result)
    elif decision == "REJECT":
        REJECTED.append(result)


def classify_candidate(candidate: dict, result: dict, duplicate_status: str = "UNIQUE") -> tuple[str, str, dict]:
    product_name = candidate.get("productName")
    website = candidate.get("website")
    description = candidate.get("description")
    identity, identity_terms = reviewer.identity_check(product_name, result)
    description_ok, description_terms = reviewer.description_match(description, result.get("coreText"))
    strong_evidence = specific_ai_evidence(result.get("coreText"))
    availability = availability_evidence(result.get("coreText"))
    page_text = str(result.get("coreText") or "")
    state = result.get("verificationStatus")
    status = result.get("httpStatus")
    reason = ""
    decision = "MANUAL_CHECK"

    if duplicate_status == "DUPLICATE_NAME_AND_DOMAIN":
        decision, reason = "REJECT", "The normalized product name and website domain already exist in the reviewed set."
    elif duplicate_status != "UNIQUE":
        decision, reason = "MANUAL_CHECK", (
            "A distinct product may share this name or domain. It was not counted because the final set "
            "requires unique normalized names and website domains."
        )
    elif status in {404, 410}:
        decision, reason = "REJECT", f"The official product website returned HTTP {status}."
    elif state != "HTTP_OK" or status is None or not 200 <= int(status) < 300:
        decision, reason = "MANUAL_CHECK", (
            "The official website could not be verified; no identity or AI claim was inferred. "
            + str(result.get("errorDetail") or state or "HTTP verification incomplete.")
        )
    elif DISCONTINUED.search(page_text):
        decision, reason = "REJECT", "The official page explicitly indicates that the product or service has ended."
    elif identity == "MISMATCH":
        decision, reason = "REJECT", "The official page identity does not match the candidate product name."
    elif NON_AI_DIRECTORY.search(str(description or "")):
        decision, reason = "REJECT", "The record describes a directory, reference, guide, or catalog rather than an AI product."
    elif not result.get("pageTitle") and not result.get("h1"):
        decision, reason = "MANUAL_CHECK", "The accessible page does not expose enough identity information."
    elif identity != "MATCH":
        decision, reason = "MANUAL_CHECK", "Product identity could not be established from the official page or domain."
    elif not strong_evidence:
        decision, reason = "MANUAL_CHECK", (
            "The official page did not provide specific first-party evidence of an AI function; "
            "generic AI wording was not counted."
        )
    elif not description_ok:
        decision, reason = "MANUAL_CHECK", "The supplied product description could not be matched to first-party page content."
    elif not availability:
        decision, reason = "MANUAL_CHECK", (
            "The product identity and AI function are supported, but no current availability or usage call-to-action "
            "was found on the official page."
        )
    elif INFRASTRUCTURE_ONLY.search(str(description or "") + " " + page_text[:5000]):
        decision, reason = "MANUAL_CHECK", (
            "The product appears to be AI infrastructure or a general developer platform; eligibility is uncertain."
        )
    elif not candidate.get("sourceListingUrl") or not reviewer.normalize_url(candidate.get("sourceListingUrl")):
        decision, reason = "MANUAL_CHECK", "A valid source listing URL was not preserved."
    else:
        decision = "VERIFIED"
        reason = (
            "Official page identity matches; first-party text describes a specific AI function; "
            "the supplied description matches page content; and current availability evidence was found."
        )

    details = {
        "identityStatus": identity,
        "identityMatchedTerms": identity_terms,
        "descriptionMatch": description_ok,
        "matchedDescriptionTerms": description_terms,
        "strongAiEvidence": bool(strong_evidence),
        "specificAiEvidence": strong_evidence,
        "availabilityEvidence": availability,
        "duplicateStatus": duplicate_status,
    }
    return decision, reason, details


def duplicate_relation(candidate: dict, indexed: dict[str, dict]) -> tuple[str, dict | None]:
    name, domain = identity_key(candidate)
    canonical = reviewer.normalize_url(candidate.get("website"))
    exact = indexed.get("by_identity", {}).get((name, domain))
    if exact:
        return "DUPLICATE_NAME_AND_DOMAIN", exact
    if canonical and canonical in indexed.get("by_url", {}):
        return "DUPLICATE_CANONICAL_URL", indexed["by_url"][canonical]
    same_domain = indexed.get("by_domain", {}).get(domain) if domain else None
    if same_domain:
        return "DOMAIN_COLLISION_DISTINCT_PRODUCT_REVIEW", same_domain
    same_name = indexed.get("by_name", {}).get(name) if name else None
    if same_name:
        return "NAME_COLLISION_POSSIBLE_DUPLICATE", same_name
    return "UNIQUE", None


def update_index(indexed: dict[str, dict], product: dict, source_name: str):
    content = product["content"]
    name, domain = normalize_name(content.get("productName")), normalized_domain(content.get("website"))
    reference = {
        "recordId": product["recordId"],
        "productName": content.get("productName"),
        "website": content.get("website"),
        "sourceName": source_name,
    }
    indexed["by_identity"][(name, domain)] = reference
    indexed["by_name"].setdefault(name, reference)
    indexed["by_domain"].setdefault(domain, reference)
    canonical = reviewer.normalize_url(content.get("website"))
    if canonical:
        indexed["by_url"][canonical] = reference


def duplicate_entry(candidate: dict, status: str, match: dict | None, reason: str):
    item = {
        "productName": candidate.get("productName"),
        "website": candidate.get("website"),
        "sourceName": candidate.get("sourceName"),
        "sourceListingUrl": candidate.get("sourceListingUrl"),
        "duplicateStatus": status,
        "matchProductName": (match or {}).get("productName"),
        "matchWebsite": (match or {}).get("website"),
        "matchRecordId": (match or {}).get("recordId"),
        "matchSourceName": (match or {}).get("sourceName"),
        "decision": "REJECT" if status == "DUPLICATE_NAME_AND_DOMAIN" else "MANUAL_CHECK",
        "reason": reason,
    }
    DUPLICATE_LOG.append(item)


def append_review(candidate: dict, result: dict, decision: str, reason: str, details: dict, prior: dict | None = None):
    product = content_record(candidate)
    evidence = make_evidence(
        candidate,
        decision,
        reason,
        result,
        extras={
            "identityStatus": details.get("identityStatus"),
            "identityMatchedTerms": details.get("identityMatchedTerms", []),
            "descriptionMatch": details.get("descriptionMatch", False),
            "matchedDescriptionTerms": details.get("matchedDescriptionTerms", []),
            "duplicateStatus": details.get("duplicateStatus", "UNIQUE"),
            "strongAiEvidence": details.get("strongAiEvidence", False),
            "priorVerification": prior,
        },
    )
    EVIDENCE.append(evidence)
    if decision == "VERIFIED":
        VERIFIED.append(product)
        VERIFIED_EVIDENCE.append(evidence)
        update_index(INDEX, product, candidate.get("sourceName") or "")
        COUNTERS["newlyVerified" if candidate.get("pool") != "combined_745" else "baselineVerified"] += 1
    else:
        append_partition(product, decision, reason)
    COUNTERS["reviewed"] += 1
    if result.get("verificationStatus") != "HTTP_OK" or not result.get("httpStatus") or not 200 <= int(result.get("httpStatus") or 0) < 300:
        COUNTERS["websiteFailures"] += 1
    if details.get("strongAiEvidence"):
        COUNTERS["strongAiEvidence"] += 1
    else:
        COUNTERS["insufficientEvidence"] += 1
    source = candidate.get("sourceName") or "Unknown"
    if decision == "VERIFIED":
        COUNTERS["sourceVerified:" + source] += 1
    return evidence


def append_duplicate_review(candidate: dict, status: str, match: dict, decision: str, reason: str):
    result = {
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "requestedUrl": reviewer.normalize_url(candidate.get("website")),
        "finalUrl": None,
        "verificationStatus": "NOT_FETCHED_DUPLICATE_OR_COLLISION",
        "httpStatus": None,
        "pageTitle": "",
        "metaDescription": "",
        "h1": "",
        "coreText": "",
        "aiEvidence": [],
        "strongAiEvidence": False,
        "errorDetail": reason,
        "robotsStatus": "",
    }
    details = {
        "identityStatus": "UNVERIFIED",
        "descriptionMatch": False,
        "duplicateStatus": status,
    }
    evidence = make_evidence(
        candidate,
        decision,
        reason,
        result,
        extras={
            "identityStatus": details["identityStatus"],
            "descriptionMatch": False,
            "duplicateStatus": status,
            "duplicateMatch": match,
        },
    )
    EVIDENCE.append(evidence)
    append_partition(content_record(candidate), decision, reason)
    COUNTERS["reviewed"] += 1
    if candidate.get("pool") != "combined_745":
        COUNTERS["candidateRecordsProcessed"] += 1
    evidence["duplicateMatch"] = match
    duplicate_entry(candidate, status, match, reason)
    return evidence


def audit_batch(candidates: list[dict], indexed: dict[str, dict], is_baseline: bool = False):
    fetch_items = []
    batch_index = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in indexed.items()
    }
    for candidate in candidates:
        name, domain = identity_key(candidate)
        if not name or not domain:
            result = {
                "checkedAt": datetime.now(timezone.utc).isoformat(),
                "requestedUrl": reviewer.normalize_url(candidate.get("website")),
                "finalUrl": None,
                "verificationStatus": "MISSING_OR_INVALID_URL",
                "httpStatus": None,
                "pageTitle": "",
                "metaDescription": "",
                "h1": "",
                "coreText": "",
                "aiEvidence": [],
                "strongAiEvidence": False,
                "errorDetail": "Product name or valid public website URL is missing.",
                "robotsStatus": "",
            }
            decision = "MANUAL_CHECK"
            reason = "Product name or valid public website URL is missing."
            details = {"identityStatus": "UNKNOWN", "descriptionMatch": False, "duplicateStatus": "UNIQUE"}
            append_review(candidate, result, decision, reason, details)
            if not is_baseline:
                COUNTERS["candidateRecordsProcessed"] += 1
            continue
        duplicate_status, match = duplicate_relation(candidate, batch_index)
        if duplicate_status == "DUPLICATE_NAME_AND_DOMAIN":
            reason = "The normalized product name and website domain already exist in the reviewed set."
            append_duplicate_review(candidate, duplicate_status, match or {}, "REJECT", reason)
            continue
        if duplicate_status != "UNIQUE":
            reason = (
                "A distinct product may share this name or domain. It was not counted because the final set "
                "requires unique normalized names and website domains."
            )
            append_duplicate_review(candidate, duplicate_status, match or {}, "MANUAL_CHECK", reason)
            continue
        fetch_items.append(candidate)
        update_index(batch_index, content_record(candidate), candidate.get("sourceName") or "")

    results: dict[int, dict] = {}
    unique_urls: dict[str, list[int]] = defaultdict(list)
    for i, candidate in enumerate(fetch_items):
        key = reviewer.normalize_url(candidate.get("website")) or f"invalid:{i}"
        unique_urls[key].append(i)
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {
            executor.submit(verify_with_retries, fetch_items[indices[0]].get("website")): indices
            for indices in unique_urls.values()
        }
        for future in as_completed(futures):
            indices = futures[future]
            try:
                result = future.result()
            except Exception as error:
                result = {
                    "checkedAt": datetime.now(timezone.utc).isoformat(),
                    "requestedUrl": reviewer.normalize_url(fetch_items[indices[0]].get("website")),
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
                }
            for index in indices:
                results[index] = result

    for i, candidate in enumerate(fetch_items):
        result = results[i]
        decision, reason, details = classify_candidate(candidate, result)
        prior = candidate.get("priorVerification")
        if prior:
            extras = {
                "priorVerification": {
                    key: prior.get(key)
                    for key in ("checkedAt", "verificationStatus", "httpStatus", "pageTitle", "evidenceUrl", "aiEvidence")
                }
            }
        else:
            extras = None
        product = content_record(candidate)
        evidence = make_evidence(candidate, decision, reason, result, extras=extras)
        evidence.update(details)
        EVIDENCE.append(evidence)
        if decision == "VERIFIED":
            VERIFIED.append(product)
            VERIFIED_EVIDENCE.append(evidence)
            update_index(indexed, product, candidate.get("sourceName") or "")
            COUNTERS["newlyVerified" if candidate.get("pool") != "combined_745" else "baselineVerified"] += 1
        else:
            append_partition(product, decision, reason)
        COUNTERS["reviewed"] += 1
        if result.get("verificationStatus") != "HTTP_OK" or not result.get("httpStatus") or not 200 <= int(result.get("httpStatus") or 0) < 300:
            COUNTERS["websiteFailures"] += 1
        if details.get("strongAiEvidence"):
            COUNTERS["strongAiEvidence"] += 1
        else:
            COUNTERS["insufficientEvidence"] += 1
        if not is_baseline:
            COUNTERS["candidateRecordsProcessed"] += 1
        if decision == "REJECT":
            COUNTERS["rejected"] += 1
        elif decision == "MANUAL_CHECK":
            COUNTERS["manual"] += 1
        else:
            COUNTERS["verified"] += 1


def build_index(records: list[dict]) -> dict[str, dict]:
    index = {
        "by_identity": {},
        "by_name": {},
        "by_domain": {},
        "by_url": {},
    }
    for product in records:
        update_index(index, product, (product.get("source") or {}).get("name") or "")
    return index


def baseline_candidates(records: list[dict], evidence_records: list[dict]) -> list[dict]:
    evidence_by_identity = {}
    for record in evidence_records:
        key = identity_key({
            "productName": record.get("productName"),
            "website": record.get("website"),
        })
        evidence_by_identity[key] = record

    result = []
    for record in records:
        candidate = candidate_from_standard(record, "combined_745")
        prior = evidence_by_identity.get(identity_key(candidate))
        if prior:
            provenance = prior.get("sourceProvenance") or []
            if provenance:
                candidate["sourceProvenance"] = provenance
                candidate["sourceName"] = provenance[0].get("sourceName") or candidate["sourceName"]
                candidate["sourceListingUrl"] = provenance[0].get("sourceListingUrl") or candidate["sourceListingUrl"]
            candidate["priorVerification"] = prior.get("officialVerification") or {}
            candidate["sourceName"] = candidate["sourceName"] or (prior.get("source") or {}).get("name", "")
        result.append(candidate)
    return result


def build_candidate_pools() -> list[dict]:
    candidates = []

    prior_manual = read_json(PRIOR_MANUAL)
    for record in prior_manual:
        item = candidate_from_listing(record, "products_803_manual_check")
        item["priorVerification"] = {
            "checkedAt": record.get("checkedAt"),
            "verificationStatus": record.get("verificationStatus"),
            "httpStatus": record.get("httpStatus"),
            "pageTitle": record.get("pageTitle"),
            "evidenceUrl": record.get("evidenceUrl"),
            "aiEvidence": record.get("aiEvidence"),
        }
        candidates.append(item)

    initial = read_json(INITIAL_CANDIDATES)
    for record in initial:
        if record.get("decision") == "MANUAL CHECK":
            candidates.append(candidate_from_listing(record, "initial_manual_candidates"))

    merge_records = read_json(MERGE_REVIEW)
    base_names = {normalize_name((r.get("content") or {}).get("productName")) for r in read_json(BASELINE)}
    base_domains = {normalized_domain((r.get("content") or {}).get("website")) for r in read_json(BASELINE)}
    for record in merge_records:
        content = record.get("content") or {}
        name = normalize_name(content.get("productName"))
        domain = normalized_domain(content.get("website"))
        if name in base_names or domain in base_domains:
            continue
        candidates.append(candidate_from_standard(record, "products_merge_review"))

    scraped_records = read_json(SCRAPED)
    for record in scraped_records:
        item = candidate_from_standard(record, "products_scraped")
        if item.get("productName") and item.get("website"):
            candidates.append(item)

    mydentify_records = read_json(MYDENTIFY)
    for record in mydentify_records:
        url = record.get("url")
        canonical_path = record.get("canonicalPath")
        listing = None
        if canonical_path:
            listing = "https://mydentify.com" + str(canonical_path)
        candidates.append({
            "productName": record.get("name") or "",
            "website": url or "",
            "description": record.get("summary") or "",
            "category": (record.get("category") or {}).get("name"),
            "pricingModel": None,
            "startupName": None,
            "sourceName": "Mydentify",
            "sourceListingUrl": listing,
            "sourceProvenance": [{
                "sourceName": "Mydentify",
                "sourceListingUrl": listing,
                "collectedAt": RUN_STARTED,
            }] if listing else [],
            "collectedAt": RUN_STARTED,
            "sourceRecordTimestamp": record.get("updatedAt"),
            "sourceRecordTimestampType": "Mydentify updatedAt",
            "originalSource": {"name": "Mydentify", "url": listing},
            "originalRecord": record,
            "pool": "mydentify_approved",
        })

    raw_ignlab = read_json(IG_RAW)
    raw_index = {}
    for record in raw_ignlab:
        raw_index[(normalize_name(record.get("name")), normalized_domain(record.get("url")))] = record
    offline = read_json(IG_OFFLINE)
    quality = {
        (normalize_name(row.get("productName")), normalized_domain(row.get("website"))): row.get("offlineReviewStatus")
        for row in offline
    }
    ignlab_records = read_json(IG_CANDIDATES)
    ignlab_candidates = []
    for record in ignlab_records:
        key = (normalize_name(record.get("productName")), normalized_domain(record.get("website")))
        raw = raw_index.get(key, {})
        listing_url = raw.get("listing_url")
        if not listing_url:
            listing_url = record.get("sourceUrl")
        candidate = candidate_from_listing({
            **record,
            "sourceProvenance": [{
                "sourceName": "Ignlab",
                "sourceListingUrl": listing_url,
                "collectedAt": RUN_STARTED,
            }] if listing_url else [],
        }, "ignlab_candidates")
        candidate["sourceName"] = "Ignlab"
        candidate["sourceListingUrl"] = listing_url
        candidate["collectedAt"] = RUN_STARTED
        candidate["sourceRecordTimestamp"] = raw.get("created_at")
        candidate["sourceRecordTimestampType"] = "Ignlab listing created_at"
        candidate["originalRecord"] = {**record, "originalIgnlabListing": raw}
        candidate["qualityPriority"] = 0 if quality.get(key) == "LIKELY_AI_REVIEW" else (
            1 if quality.get(key) == "MANUAL_REVIEW" else 2
        )
        ignlab_candidates.append(candidate)
    candidates.extend(sorted(ignlab_candidates, key=lambda x: (x.get("qualityPriority", 2), x.get("productName", "").casefold())))
    return candidates


def load_used_listing_urls() -> set[str]:
    used = set()
    for path in (INITIAL_CANDIDATES, NEW_SOURCE_RAW):
        rows = read_json(path)
        for row in rows:
            urls = []
            if row.get("sourceListingUrl"):
                urls.append(row.get("sourceListingUrl"))
            for provenance in row.get("sourceProvenance") or []:
                urls.append(provenance.get("sourceListingUrl"))
            for url in urls:
                normalized = reviewer.normalize_url(url)
                if normalized:
                    used.add(normalized)
    return used


def discover_more_listing_urls(used: set[str]) -> list[tuple[str, str]]:
    source_urls: list[tuple[str, str]] = []

    futurepedia_sitemap = discovery.FUTUREPEDIA_SITEMAP
    if reviewer.robots_allowed(futurepedia_sitemap)[0] is True:
        reviewer.throttle_request(reviewer.host_for(futurepedia_sitemap))
        for url in discovery.discover_futurepedia_urls():
            normalized = reviewer.normalize_url(url)
            if normalized and normalized not in used:
                source_urls.append(("Futurepedia", normalized))

    futuretools_sitemap = discovery.FUTURETOOLS_SITEMAP
    if reviewer.robots_allowed(futuretools_sitemap)[0] is True:
        reviewer.throttle_request(reviewer.host_for(futuretools_sitemap))
        try:
            child_sitemaps = discovery.parse_sitemap(futuretools_sitemap)
        except Exception as error:
            COUNTERS["directoryDiscoveryErrors"] += 1
            print(f"FutureTools sitemap error: {error}")
            child_sitemaps = []
        tool_sitemaps = [
            url for url in child_sitemaps
            if re.search(r"/tools-\d+\.xml$", urlsplit(url).path)
        ]
        tool_urls = []
        for sitemap_url in tool_sitemaps:
            if reviewer.robots_allowed(sitemap_url)[0] is not True:
                COUNTERS["directoryRobotsSkipped"] += 1
                continue
            reviewer.throttle_request(reviewer.host_for(sitemap_url))
            try:
                tool_urls.extend(discovery.parse_sitemap(sitemap_url))
            except Exception as error:
                COUNTERS["directoryDiscoveryErrors"] += 1
                print(f"FutureTools child sitemap error: {error}")
        for url in discovery.unique_urls(tool_urls):
            if "/tools/" not in urlsplit(url).path:
                continue
            normalized = reviewer.normalize_url(url)
            if normalized and normalized not in used:
                source_urls.append(("FutureTools", normalized))

    aixploria_directory = discovery.AIXPLORIA_DIRECTORY
    if reviewer.robots_allowed(aixploria_directory)[0] is True:
        reviewer.throttle_request(reviewer.host_for(aixploria_directory))
        try:
            for url in discovery.discover_aixploria_urls():
                normalized = reviewer.normalize_url(url)
                if normalized and normalized not in used:
                    source_urls.append(("Aixploria", normalized))
        except Exception as error:
            COUNTERS["directoryDiscoveryErrors"] += 1
            print(f"Aixploria listing discovery error: {error}")

    seen = set()
    unique = []
    for source_name, url in source_urls:
        if url not in seen:
            seen.add(url)
            unique.append((source_name, url))
    return unique


def extract_listing_with_retries(source_name: str, url: str) -> tuple[dict | None, bool]:
    for attempt in range(3):
        allowed, status = reviewer.robots_allowed(url)
        if allowed is not True:
            COUNTERS["directoryRobotsSkipped"] += 1
            return None, False
        reviewer.throttle_request(reviewer.host_for(url))
        raw, candidate, blocking = discovery.extract_listing(source_name, url)
        fetch_status = raw.get("fetchStatus")
        if fetch_status == 429 or (isinstance(fetch_status, int) and fetch_status in {500, 502, 503, 504}):
            if attempt < 2:
                time.sleep(2 ** attempt)
                COUNTERS["directoryRetries"] += 1
                continue
            return None, True
        if raw.get("fetchStatus") == "ERROR" and attempt < 2:
            time.sleep(2 ** attempt)
            COUNTERS["directoryRetries"] += 1
            continue
        return candidate, bool(blocking or fetch_status == 403)
    return None, False


def discover_and_review_more(indexed: dict[str, dict]):
    used = load_used_listing_urls()
    listing_urls = discover_more_listing_urls(used)
    print(f"Additional permitted directory listing URLs discovered: {len(listing_urls)}")
    by_source = defaultdict(list)
    for source_name, url in listing_urls:
        by_source[source_name].append(url)
    stopped_sources = set()
    total_candidates = 0

    for source_name in ("Futurepedia", "FutureTools", "Aixploria"):
        urls = by_source.get(source_name, [])
        print(f"Checking additional {source_name} listings: {len(urls)}")
        for offset in range(0, len(urls), BATCH_SIZE):
            if len(VERIFIED) >= TARGET or source_name in stopped_sources:
                break
            batch_urls = urls[offset:offset + BATCH_SIZE]
            extracted = []
            with ThreadPoolExecutor(max_workers=WORKERS) as executor:
                future_map = {
                    executor.submit(extract_listing_with_retries, source_name, url): url
                    for url in batch_urls
                }
                for future in as_completed(future_map):
                    url = future_map[future]
                    try:
                        candidate, blocked = future.result()
                    except Exception as error:
                        COUNTERS["directoryDiscoveryErrors"] += 1
                        candidate, blocked = None, False
                        print(f"{source_name} listing error at {url}: {error}")
                    if blocked:
                        stopped_sources.add(source_name)
                    if candidate and candidate.get("productName") and candidate.get("website"):
                        extracted.append(candidate_from_listing(candidate, "additional_" + source_name.lower()))
                        COUNTERS["directoryListingsParsed"] += 1
            total_candidates += len(extracted)
            if extracted:
                remaining = TARGET - len(VERIFIED)
                for offset_candidate in range(0, len(extracted), min(BATCH_SIZE, remaining or 1)):
                    if len(VERIFIED) >= TARGET:
                        break
                    batch = extracted[offset_candidate:offset_candidate + min(BATCH_SIZE, TARGET - len(VERIFIED))]
                    audit_batch(batch, indexed)
            print(
                f"{source_name} listing batch {offset // BATCH_SIZE + 1}: "
                f"parsed {len(extracted)} candidates; verified total {len(VERIFIED)}/{TARGET}"
            )
    COUNTERS["additionalDirectoryCandidates"] = total_candidates


def source_counts() -> dict[str, int]:
    counts = Counter()
    for product in VERIFIED:
        counts[(product.get("source") or {}).get("name") or "Unknown"] += 1
    return dict(sorted(counts.items()))


def validate_final(products: list[dict], evidence: list[dict], input_hashes: dict[str, str]):
    if len(products) != min(TARGET, len(VERIFIED)):
        raise ValueError("Verified product output count does not match the in-memory verified set.")
    if len({product.get("recordId") for product in products}) != len(products):
        raise ValueError("Stable record IDs are not unique.")
    names = [normalize_name((product.get("content") or {}).get("productName")) for product in products]
    domains = [normalized_domain((product.get("content") or {}).get("website")) for product in products]
    if not all(names) or len(set(names)) != len(names):
        raise ValueError("Verified output has missing or duplicate normalized product names.")
    if not all(domains) or len(set(domains)) != len(domains):
        raise ValueError("Verified output has missing or duplicate normalized website domains.")
    required_top = {"schemaVersion", "recordType", "source", "content", "collectedAt", "recordId"}
    required_content = {"productName", "startupName", "website", "description", "category", "pricingModel"}
    evidence_ids = {row.get("recordId") for row in evidence if row.get("verificationDecision") == "VERIFIED"}
    for product in products:
        if not required_top.issubset(product):
            raise ValueError(f"Missing standard schema fields for {product.get('recordId')}.")
        content = product["content"]
        if not required_content.issubset(content):
            raise ValueError(f"Missing content schema fields for {product.get('recordId')}.")
        if product.get("schemaVersion") != "1.0" or product.get("recordType") != "PRODUCT":
            raise ValueError(f"Invalid standard schema identifiers for {product.get('recordId')}.")
        if not reviewer.normalize_url(content.get("website")):
            raise ValueError(f"Invalid official website URL for {product.get('recordId')}.")
        if not content.get("description"):
            raise ValueError(f"Missing product description for {product.get('recordId')}.")
        if product["recordId"] not in evidence_ids:
            raise ValueError(f"No corresponding verification evidence for {product.get('recordId')}.")
    for path, expected in input_hashes.items():
        if digest(Path(path)) != expected:
            raise ValueError(f"Source input changed during review: {path}")


def make_report(input_hashes: dict[str, str]) -> str:
    source_counts_result = source_counts()
    failure_details = [
        row for row in EVIDENCE
        if row.get("verification", {}).get("verificationStatus") != "NOT_FETCHED_DUPLICATE_OR_COLLISION"
        and (
            row.get("verification", {}).get("verificationStatus") != "HTTP_OK"
            or not row.get("verification", {}).get("httpStatus")
            or not 200 <= int(row.get("verification", {}).get("httpStatus") or 0) < 300
        )
    ]
    confirmed_duplicates = sum(
        row.get("duplicateStatus") == "DUPLICATE_NAME_AND_DOMAIN"
        for row in EVIDENCE
    )
    possible_collisions = sum(
        row.get("duplicateStatus") not in {"UNIQUE", "DUPLICATE_NAME_AND_DOMAIN"}
        for row in EVIDENCE
    )
    gap = max(0, TARGET - len(VERIFIED))
    lines = [
        "GraphOne Data Intelligence — 1,000 AI Product Verification",
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        "",
        f"Existing combined baseline audited: {COUNTERS.get('baselineAudited', 0)}",
        f"Existing baseline verified: {COUNTERS.get('baselineVerified', 0)}",
        f"Additional candidates reviewed: {max(0, COUNTERS.get('reviewed', 0) - COUNTERS.get('baselineAudited', 0))}",
        f"Newly discovered products verified: {COUNTERS.get('newlyVerified', 0)}",
        f"Total verified unique products: {len(VERIFIED)}",
        f"Remaining to target: {gap}",
        f"Manual check: {len(MANUAL)}",
        f"Rejected: {len(REJECTED)}",
        f"Confirmed duplicate records excluded: {confirmed_duplicates}",
        f"Possible name/domain collisions sent to manual check: {possible_collisions}",
        f"Website verification failures or incomplete checks (excluding duplicate skips): {len(failure_details)}",
        f"Reviewed records with strong first-party AI evidence: {COUNTERS.get('strongAiEvidence', 0)}",
        f"Verified records with strong first-party AI evidence: {len(VERIFIED_EVIDENCE)}",
        f"Reviewed records without sufficient first-party AI evidence: {COUNTERS.get('insufficientEvidence', 0)}",
        f"New directory listings parsed: {COUNTERS.get('directoryListingsParsed', 0)}",
        f"Directory listings skipped by robots.txt: {COUNTERS.get('directoryRobotsSkipped', 0)}",
        f"Transient request retries: {COUNTERS.get('transientRetries', 0) + COUNTERS.get('directoryRetries', 0)}",
        "",
        "Verified products by primary source:",
    ]
    lines.extend(f"- {name}: {count}" for name, count in source_counts_result.items())
    lines.extend([
        "",
        "Output files:",
    ])
    lines.extend(f"- {path.name}: {path.resolve()}" for path in OUTPUTS.values())
    lines.extend([
        "",
        "Validation",
        f"- Verified JSON count: {len(VERIFIED)}",
        f"- Verified CSV data rows: {len(VERIFIED)}",
        f"- Evidence entries linked to verified records: {len(VERIFIED_EVIDENCE)}",
        f"- Unique normalized names: {len({normalize_name((p.get('content') or {}).get('productName')) for p in VERIFIED})}",
        f"- Unique normalized domains: {len({normalized_domain((p.get('content') or {}).get('website')) for p in VERIFIED})}",
        "- All source dataset hashes checked unchanged.",
        "",
        "Method and limitations",
        "- Approval required a matching product identity, specific AI-task evidence in first-party page text, description overlap, a current availability signal, a permitted/valid source listing URL, and no unresolved duplicate/domain collision.",
        "- Generic AI keywords, directory SEO titles, HTTP 200 alone, and source descriptions alone were not treated as AI proof.",
        "- Robots-disallowed, robots-unverified, inaccessible, ambiguous, or eligibility-uncertain products remain MANUAL_CHECK.",
        "- AI infrastructure or general developer platforms with uncertain collection eligibility remain MANUAL_CHECK.",
        "- The availability check establishes a live first-party offering signal; it is not an independent audit of release cadence or corporate status.",
        "- Previously rejected records were not restored without new first-party evidence that resolves the original rejection reason.",
        "- If the verified total is below 1,000, no records were fabricated or promoted to close the gap.",
        "",
        "Website verification failures (first 40):",
    ])
    lines.extend(
        f"- {row.get('productName')}: {row.get('verification', {}).get('verificationStatus')} "
        f"HTTP {row.get('verification', {}).get('httpStatus')} — "
        f"{row.get('verification', {}).get('errorDetail') or row.get('reviewReason')}"
        for row in failure_details[:40]
    )
    if not failure_details:
        lines.append("- None.")
    return "\n".join(lines) + "\n"


def write_outputs(input_hashes: dict[str, str]):
    if len(VERIFIED) > TARGET:
        raise ValueError("Internal error: verified output exceeded the requested target.")
    products = VERIFIED[:TARGET]
    evidence = EVIDENCE
    csv_fields = [
        "recordId", "schemaVersion", "recordType", "sourceName", "sourceUrl",
        "productName", "startupName", "website", "description", "category",
        "pricingModel", "collectedAt",
    ]
    report = make_report(input_hashes)
    temp_paths = {
        key: path.with_name(path.name + f".{os.getpid()}.tmp")
        for key, path in OUTPUTS.items()
    }
    for path in OUTPUTS.values():
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite existing output: {path}")
    try:
        with temp_paths["verified_json"].open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(products, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        with temp_paths["verified_csv"].open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=csv_fields)
            writer.writeheader()
            for product in products:
                content = product["content"]
                source = product.get("source") or {}
                writer.writerow({
                    "recordId": product.get("recordId"),
                    "schemaVersion": product.get("schemaVersion"),
                    "recordType": product.get("recordType"),
                    "sourceName": source.get("name"),
                    "sourceUrl": source.get("url"),
                    **content,
                    "collectedAt": product.get("collectedAt"),
                })
        with temp_paths["evidence_json"].open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(evidence, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        with temp_paths["manual_json"].open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(MANUAL, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        with temp_paths["rejected_json"].open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(REJECTED, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        duplicate_fields = [
            "productName", "website", "sourceName", "sourceListingUrl", "duplicateStatus",
            "matchProductName", "matchWebsite", "matchRecordId", "matchSourceName", "decision", "reason",
        ]
        with temp_paths["duplicates_csv"].open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=duplicate_fields)
            writer.writeheader()
            writer.writerows(DUPLICATE_LOG)
        with temp_paths["report"].open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(report)

        with temp_paths["verified_json"].open(encoding="utf-8") as stream:
            parsed_products = json.load(stream)
        with temp_paths["evidence_json"].open(encoding="utf-8") as stream:
            parsed_evidence = json.load(stream)
        with temp_paths["manual_json"].open(encoding="utf-8") as stream:
            parsed_manual = json.load(stream)
        with temp_paths["rejected_json"].open(encoding="utf-8") as stream:
            parsed_rejected = json.load(stream)
        with temp_paths["verified_csv"].open(encoding="utf-8-sig", newline="") as stream:
            csv_reader = csv.DictReader(stream)
            parsed_csv = list(csv_reader)
            if csv_reader.fieldnames != csv_fields:
                raise ValueError("Verified CSV columns are invalid.")
        if len(parsed_products) != len(products) or len(parsed_csv) != len(products):
            raise ValueError("Staged verified JSON/CSV counts do not match.")
        if len(parsed_evidence) != len(evidence) or len(parsed_manual) != len(MANUAL) or len(parsed_rejected) != len(REJECTED):
            raise ValueError("Staged evidence/manual/rejected counts do not match.")
        validate_final(parsed_products, parsed_evidence, input_hashes)
        for key, path in OUTPUTS.items():
            os.replace(temp_paths[key], path)
        for path, expected in input_hashes.items():
            if digest(Path(path)) != expected:
                raise ValueError(f"Source input changed during output commit: {path}")
        validate_final(read_json(OUTPUTS["verified_json"]), read_json(OUTPUTS["evidence_json"]), input_hashes)
        with OUTPUTS["verified_csv"].open(encoding="utf-8-sig", newline="") as stream:
            if len(list(csv.DictReader(stream))) != len(products):
                raise ValueError("Committed verified CSV failed final row-count validation.")
    except Exception:
        for path in temp_paths.values():
            if path.exists():
                path.unlink()
        raise


def main():
    global INDEX
    required = [
        BASELINE, BASELINE_EVIDENCE, PRIOR_APPROVED, PRIOR_REVIEW, PRIOR_MANUAL,
        INITIAL_CANDIDATES, MERGE_REVIEW, SCRAPED, MYDENTIFY, IG_RAW, IG_CANDIDATES,
        IG_OFFLINE, NEW_SOURCE_RAW,
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Required input file(s) missing: " + ", ".join(str(path) for path in missing))
    preexisting_outputs = [path for path in OUTPUTS.values() if path.exists()]
    if preexisting_outputs:
        raise FileExistsError("Refusing to overwrite output(s): " + ", ".join(map(str, preexisting_outputs)))

    input_hashes = data_input_hashes()
    baseline = read_json(BASELINE)
    baseline_evidence = read_json(BASELINE_EVIDENCE)
    approved_prior = read_json(PRIOR_APPROVED)
    if len(baseline) != 745 or len(approved_prior) != 468:
        raise ValueError(f"Unexpected baseline counts: combined={len(baseline)}, prior approved={len(approved_prior)}.")
    if len(baseline_evidence) != 468:
        raise ValueError(f"Expected 468 preserved evidence records; found {len(baseline_evidence)}.")

    base = baseline_candidates(baseline, baseline_evidence)
    INDEX = build_index([])
    print(f"Auditing all {len(base)} baseline records with fresh official-site requests.")
    for offset in range(0, len(base), BATCH_SIZE):
        batch = base[offset:offset + BATCH_SIZE]
        audit_batch(batch, INDEX, is_baseline=True)
        COUNTERS["baselineAudited"] += len(batch)
        print(
            f"Baseline checked: {COUNTERS['baselineAudited']}/{len(base)}; "
            f"verified unique total {len(VERIFIED)}"
        )

    candidate_queue = build_candidate_pools()
    print(f"Eligible candidate queue assembled: {len(candidate_queue)} records.")
    processed = 0
    cursor = 0
    while cursor < len(candidate_queue) and len(VERIFIED) < TARGET:
        batch = []
        batch_target = min(BATCH_SIZE, TARGET - len(VERIFIED))
        while cursor < len(candidate_queue) and len(batch) < batch_target:
            candidate = candidate_queue[cursor]
            cursor += 1
            name, domain = identity_key(candidate)
            if not name or not domain:
                audit_batch([candidate], INDEX)
                processed += 1
                continue
            duplicate_status, match = duplicate_relation(candidate, INDEX)
            if duplicate_status == "DUPLICATE_NAME_AND_DOMAIN":
                reason = "The normalized product name and website domain already exist in the reviewed set."
                append_duplicate_review(candidate, duplicate_status, match or {}, "REJECT", reason)
                processed += 1
                continue
            if duplicate_status != "UNIQUE":
                reason = (
                    "A distinct product may share this name or domain. It was not counted because the final set "
                    "requires unique normalized names and website domains."
                )
                append_duplicate_review(candidate, duplicate_status, match or {}, "MANUAL_CHECK", reason)
                processed += 1
                continue
            batch.append(candidate)
        if batch and len(VERIFIED) < TARGET:
            audit_batch(batch, INDEX)
            processed += len(batch)
            print(
                f"Candidates checked: {processed}; verified unique total {len(VERIFIED)}/{TARGET}; "
                f"manual {len(MANUAL)}; rejected {len(REJECTED)}"
            )

    if len(VERIFIED) < TARGET:
        discover_and_review_more(INDEX)

    if len(VERIFIED) > TARGET:
        VERIFIED[:] = VERIFIED[:TARGET]
        VERIFIED_EVIDENCE[:] = VERIFIED_EVIDENCE[:TARGET]
    if len(VERIFIED) < TARGET:
        print(f"Available reviewed pools did not establish the target; verified {len(VERIFIED)}/{TARGET}.")

    if len(VERIFIED) != len(VERIFIED_EVIDENCE):
        raise ValueError("Verified products and their evidence records are not one-to-one.")
    for evidence in VERIFIED_EVIDENCE:
        if not evidence.get("sourceListingUrl"):
            raise ValueError(f"Verified record lacks source listing URL: {evidence.get('recordId')}")
        if not evidence.get("verification", {}).get("aiEvidence"):
            raise ValueError(f"Verified record lacks specific first-party AI evidence: {evidence.get('recordId')}")

    write_outputs(input_hashes)
    print(make_report(input_hashes))


if __name__ == "__main__":
    main()
