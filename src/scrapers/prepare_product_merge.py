
import json
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"

EXISTING_FILE = DATA_DIR / "products.json"
NEW_FILE = DATA_DIR / "ignlab_normalized_products.json"
OUTPUT_FILE = DATA_DIR / "products_merge_review.json"


def normalize_domain(url):
    try:
        return urlparse(str(url or "").strip()).netloc.lower().removeprefix("www.")
    except ValueError:
        return ""


def main():
    with open(EXISTING_FILE, encoding="utf-8") as f:
        existing = json.load(f)

    with open(NEW_FILE, encoding="utf-8") as f:
        new_records = json.load(f)

    existing_domains = {
        normalize_domain(x.get("content", {}).get("website"))
        for x in existing
    }
    existing_domains.discard("")

    merge_candidates = []
    duplicates = []

    for item in new_records:
        domain = normalize_domain(item.get("content", {}).get("website"))

        if not domain or domain in existing_domains:
            duplicates.append(item)
            continue

        merge_candidates.append(item)

    review = existing + merge_candidates

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(review, f, indent=2, ensure_ascii=False)

    print("Existing products:", len(existing))
    print("New candidates:", len(new_records))
    print("Potential duplicates:", len(duplicates))
    print("New candidates retained:", len(merge_candidates))
    print("Combined review records:", len(review))
    print("Saved:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
