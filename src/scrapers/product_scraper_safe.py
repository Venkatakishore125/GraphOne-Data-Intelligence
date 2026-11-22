
import csv
import json
import time
import requests

from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse

# Project paths
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"

JSON_FILE = DATA_DIR / "products_scraped.json"
CSV_FILE = DATA_DIR / "products_scraped.csv"

# Public data sources
AI_INDEX_URL = "https://index.percall.dev/api/index.json"

LAUNCH_LLAMA_API = (
    "https://kxdushqmihjyuddcwkpw.supabase.co"
    "/functions/v1/api-v1/products"
)

TARGET_COUNT = 1000

AI_KEYWORDS = {
    "ai", "artificial intelligence", "machine learning",
    "llm", "generative", "chatbot", "agent", "automation",
    "copilot", "image generation", "video generation",
    "speech", "transcription", "natural language",
    "rag", "computer vision", "neural network"
}

SEARCH_TERMS = [
    "AI", "artificial intelligence", "AI agent",
    "AI writing", "AI image", "AI video",
    "AI chatbot", "AI productivity", "machine learning",
    "AI developer tools", "AI automation", "LLM"
]

HEADERS = {
    "User-Agent": "GraphOne-Data-Intelligence/1.0",
    "Accept": "application/json"
}


def get_domain(url):
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def normalize_pricing(value):
    if not value:
        return None

    value = str(value).strip().lower()

    mapping = {
        "free": "FREE",
        "freemium": "FREEMIUM",
        "paid": "PAID",
        "enterprise": "ENTERPRISE"
    }

    return mapping.get(value)


def is_ai_product(name, description, tags):
    text = " ".join([
        str(name or ""),
        str(description or ""),
        " ".join(tags if isinstance(tags, list) else [])
    ]).lower()

    return any(keyword in text for keyword in AI_KEYWORDS)


def make_record(
    name,
    website,
    description,
    category,
    pricing,
    source_name,
    source_url,
    startup_name=None
):
    if not name or not website:
        return None

    website = str(website).strip()

    if not website.startswith(("https://", "http://")):
        return None

    return {
        "schemaVersion": "1.0",
        "recordType": "PRODUCT",
        "source": {
            "name": source_name,
            "url": source_url
        },
        "content": {
            "productName": str(name).strip(),
            "startupName": startup_name,
            "website": website,
            "description": description,
            "category": category,
            "pricingModel": normalize_pricing(pricing)
        },
        "collectedAt": datetime.now(timezone.utc).isoformat()
    }


def fetch_ai_index():
    print("Fetching AI Product Index...")

    records = []

    try:
        response = requests.get(
            AI_INDEX_URL,
            headers=HEADERS,
            timeout=30
        )
        response.raise_for_status()

        data = response.json()
        listings = data.get("listings", [])

        for item in listings:
            name = item.get("name")
            website = item.get("url")
            description = item.get("description")
            tags = item.get("tags", [])

            if not is_ai_product(name, description, tags):
                continue

            record = make_record(
                name=name,
                website=website,
                description=description,
                category=item.get("category"),
                pricing=item.get("pricing"),
                source_name="AI Product Index",
                source_url=AI_INDEX_URL
            )

            if record:
                records.append(record)

    except (requests.RequestException, ValueError) as error:
        print("AI Product Index error:", error)

    print("AI Product Index records:", len(records))
    return records


def fetch_launch_llama():
    print("Fetching Launch Llama products...")

    records = []

    for term in SEARCH_TERMS:
        offset = 0
        limit = 100

        while True:
            params = {
                "q": term,
                "limit": limit,
                "offset": offset
            }

            try:
                response = requests.get(
                    LAUNCH_LLAMA_API,
                    params=params,
                    headers=HEADERS,
                    timeout=30
                )
                response.raise_for_status()

                data = response.json()

                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    items = data.get(
                        "products",
                        data.get("data", data.get("results", []))
                    )
                else:
                    items = []

                if not isinstance(items, list) or not items:
                    break

                for item in items:
                    name = item.get("name")
                    website = item.get("website") or item.get("url")

                    description = (
                        item.get("description")
                        or item.get("tagline")
                    )

                    tags = item.get("tags", [])

                    if isinstance(tags, list):
                        tags = [
                            t.get("name", "") if isinstance(t, dict)
                            else str(t)
                            for t in tags
                        ]
                    else:
                        tags = []

                    if not is_ai_product(name, description, tags):
                        continue

                    record = make_record(
                        name=name,
                        website=website,
                        description=description,
                        category=item.get("category"),
                        pricing=item.get("pricing"),
                        source_name="Launch Llama",
                        source_url="https://tools.launchllama.co/"
                    )

                    if record:
                        records.append(record)

                if len(items) < limit:
                    break

                offset += limit
                time.sleep(0.5)

            except (requests.RequestException, ValueError) as error:
                print(f"Launch Llama error for {term}: {error}")
                break

    print("Launch Llama records:", len(records))
    return records


def deduplicate(records):
    unique = {}

    for record in records:
        domain = get_domain(
            record.get("content", {}).get("website", "")
        )

        if not domain:
            continue

        if domain not in unique:
            unique[domain] = record

    return list(unique.values())


def save_products(records):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing records first
    existing_products = []

    if JSON_FILE.exists():
        try:
            with open(JSON_FILE, "r", encoding="utf-8") as file:
                existing_products = json.load(file)

            if not isinstance(existing_products, list):
                raise ValueError("Existing product JSON is not a list")

        except (json.JSONDecodeError, OSError, ValueError) as error:
            raise RuntimeError(
                f"Cannot safely read existing products: {error}"
            )

    # Combine old and new records
    combined = existing_products + records

    # Remove duplicate websites
    final_products = deduplicate(combined)

    # Save JSON
    with open(JSON_FILE, "w", encoding="utf-8") as file:
        json.dump(
            final_products,
            file,
            indent=2,
            ensure_ascii=False
        )

    # Save CSV
    if final_products:
        fieldnames = [
            "schemaVersion",
            "recordType",
            "source.name",
            "source.url",
            "content.productName",
            "content.startupName",
            "content.website",
            "content.description",
            "content.category",
            "content.pricingModel",
            "collectedAt"
        ]

        with open(
            CSV_FILE,
            "w",
            newline="",
            encoding="utf-8-sig"
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=fieldnames
            )

            writer.writeheader()

            for product in final_products:
                content = product.get("content", {})
                source = product.get("source", {})

                writer.writerow({
                    "schemaVersion": product.get("schemaVersion"),
                    "recordType": product.get("recordType"),
                    "source.name": source.get("name"),
                    "source.url": source.get("url"),
                    "content.productName": content.get("productName"),
                    "content.startupName": content.get("startupName"),
                    "content.website": content.get("website"),
                    "content.description": content.get("description"),
                    "content.category": content.get("category"),
                    "content.pricingModel": content.get("pricingModel"),
                    "collectedAt": product.get("collectedAt")
                })

    print("Existing products:", len(existing_products))
    print("New records received:", len(records))
    print("Total unique products:", len(final_products))


def scrape_products():
    print("Starting AI product collection...")

    records = []

    records.extend(fetch_ai_index())
    records.extend(fetch_launch_llama())

    new_products = deduplicate(records)

    save_products(new_products)

    # Read final count
    with open(JSON_FILE, "r", encoding="utf-8") as file:
        final_products = json.load(file)

    print("\nProduct scraping completed!")
    print("Total unique products:", len(final_products))
    print("Target:", TARGET_COUNT)
    print("Remaining:", max(0, TARGET_COUNT - len(final_products)))
    print("JSON:", JSON_FILE)
    print("CSV:", CSV_FILE)

    if len(final_products) >= TARGET_COUNT:
        print("Target reached!")
    else:
        print("More genuine product sources are required.")


if __name__ == "__main__":
    scrape_products()
