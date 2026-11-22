
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"

INPUT_FILE = DATA_DIR / "ignlab_offline_review.json"
OUTPUT_FILE = DATA_DIR / "ignlab_likely_ai_review.json"

with open(INPUT_FILE, encoding="utf-8") as f:
    records = json.load(f)

selected = [
    {
        "productName": x.get("productName"),
        "website": x.get("website"),
        "description": x.get("description"),
        "category": x.get("category"),
        "tags": x.get("tags"),
        "sourceName": x.get("sourceName"),
        "sourceUrl": x.get("sourceUrl"),
        "matchedStrongTerms": x.get("matchedStrongTerms"),
        "validationStatus": "PENDING"
    }
    for x in records
    if x.get("offlineReviewStatus") == "LIKELY_AI_REVIEW"
]

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(selected, f, indent=2, ensure_ascii=False)

print("Likely AI candidates exported:", len(selected))
print("Saved:", OUTPUT_FILE)
