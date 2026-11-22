
import json
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"

INPUT_FILE = DATA_DIR / "ignlab_evidence_review.json"
OUTPUT_FILE = DATA_DIR / "ignlab_normalized_products.json"


def normalize_pricing(value):
    if not value:
        return None

    mapping = {
        "free": "FREE",
        "freemium": "FREEMIUM",
        "paid": "PAID",
        "enterprise": "ENTERPRISE"
    }

    return mapping.get(str(value).strip().lower())


def main():
    with open(INPUT_FILE, encoding="utf-8") as f:
        candidates = json.load(f)

    products = []

    for item in candidates:
        original = item.get("originalListing", {})

        products.append({
            "schemaVersion": "1.0",
            "recordType": "PRODUCT",
            "source": {
                "name": "Ignlab",
                "url": "https://launch.ignlab.net/"
            },
            "content": {
                "productName": item.get("productName"),
                "startupName": None,
                "website": item.get("website"),
                "description": item.get("description"),
                "category": item.get("category"),
                "pricingModel": normalize_pricing(
                    original.get("pricing")
                )
            },
            "sourceEvidence": {
                "listingId": item.get("ignlabListingId"),
                "originalPricing": original.get("pricing"),
                "validationStatus": "PENDING"
            },
            "collectedAt": datetime.now(timezone.utc).isoformat()
        })

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)

    print("Normalized candidates:", len(products))
    print("Saved:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
