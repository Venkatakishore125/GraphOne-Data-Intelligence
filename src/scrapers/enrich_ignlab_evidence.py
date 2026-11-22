
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"

RAW_FILE = DATA_DIR / "ignlab_raw.json"
CANDIDATE_FILE = DATA_DIR / "ignlab_likely_ai_review.json"
OUTPUT_FILE = DATA_DIR / "ignlab_evidence_review.json"


def main():
    with open(RAW_FILE, encoding="utf-8") as f:
        raw_records = json.load(f)

    with open(CANDIDATE_FILE, encoding="utf-8") as f:
        candidates = json.load(f)

    # Match by original listing ID when available.
    raw_by_id = {
        str(item.get("id")): item
        for item in raw_records
        if item.get("id") is not None
    }

    results = []

    for candidate in candidates:
        matched = None

        # Prefer exact product name + website match.
        for item in raw_records:
            if (
                str(item.get("name", "")).strip().lower()
                == str(candidate.get("productName", "")).strip().lower()
                and str(item.get("url", "")).strip().lower()
                == str(candidate.get("website", "")).strip().lower()
            ):
                matched = item
                break

        record = dict(candidate)

        if matched:
            record["ignlabListingId"] = matched.get("id")
            record["originalListing"] = matched
            record["evidenceStatus"] = "SOURCE_RECORD_MATCHED"
        else:
            record["ignlabListingId"] = None
            record["originalListing"] = None
            record["evidenceStatus"] = "SOURCE_RECORD_NOT_FOUND"

        record["validationStatus"] = "PENDING"
        results.append(record)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    matched_count = sum(
        x["evidenceStatus"] == "SOURCE_RECORD_MATCHED"
        for x in results
    )

    print("Candidates:", len(results))
    print("Matched to original listings:", matched_count)
    print("Unmatched:", len(results) - matched_count)
    print("Saved:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
