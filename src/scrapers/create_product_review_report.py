
import json
import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"

INPUT_FILE = DATA_DIR / "ignlab_evidence_review.json"
OUTPUT_FILE = DATA_DIR / "ignlab_product_review_report.csv"

with open(INPUT_FILE, encoding="utf-8") as f:
    records = json.load(f)

with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "listing_id",
            "product_name",
            "website",
            "description",
            "category",
            "pricing",
            "matched_ai_terms",
            "review_status"
        ]
    )

    writer.writeheader()

    for item in records:
        original = item.get("originalListing", {})

        writer.writerow({
            "listing_id": item.get("ignlabListingId"),
            "product_name": item.get("productName"),
            "website": item.get("website"),
            "description": item.get("description"),
            "category": item.get("category"),
            "pricing": original.get("pricing"),
            "matched_ai_terms": ", ".join(
                item.get("matchedStrongTerms", [])
            ),
            "review_status": "PENDING"
        })

print("Review report created.")
print("Products:", len(records))
print("File:", OUTPUT_FILE)
