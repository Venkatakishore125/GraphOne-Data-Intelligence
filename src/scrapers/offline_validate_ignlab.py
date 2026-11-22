
import json
import re
from pathlib import Path
from collections import Counter
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"

INPUT_FILE = DATA_DIR / "ignlab_new_candidates.json"
OUTPUT_FILE = DATA_DIR / "ignlab_offline_review.json"

STRONG_TERMS = [
    "artificial intelligence",
    "machine learning",
    "deep learning",
    "large language model",
    "generative ai",
    "computer vision",
    "natural language processing",
    "ai-powered",
    "ai agent",
    "llm",
    "rag"
]

BROAD_TERMS = [
    "automation",
    "chatbot",
    "copilot",
    "smart assistant",
    "intelligent",
    "workflow automation"
]


def get_tags(tags):
    if isinstance(tags, list):
        return " ".join(
            str(t.get("name", "")) if isinstance(t, dict)
            else str(t)
            for t in tags
        )
    return str(tags or "")


def valid_url(url):
    parsed = urlparse(str(url or ""))
    return (
        parsed.scheme in ("http", "https")
        and bool(parsed.netloc)
    )


def main():
    with open(INPUT_FILE, encoding="utf-8") as f:
        candidates = json.load(f)

    results = []

    for item in candidates:
        name = str(item.get("productName") or "")
        description = str(item.get("description") or "")
        category = str(item.get("category") or "")
        tags = get_tags(item.get("tags"))

        searchable = " ".join([
            name, description, category, tags
        ]).lower()

        strong_matches = [
            term for term in STRONG_TERMS
            if re.search(r"\b" + re.escape(term) + r"\b", searchable)
        ]

        broad_matches = [
            term for term in BROAD_TERMS
            if re.search(r"\b" + re.escape(term) + r"\b", searchable)
        ]

        if not valid_url(item.get("website")):
            status = "REVIEW_INVALID_URL"
        elif strong_matches:
            status = "LIKELY_AI_REVIEW"
        elif broad_matches:
            status = "MANUAL_REVIEW"
        else:
            status = "INSUFFICIENT_AI_EVIDENCE"

        results.append({
            **item,
            "offlineReviewStatus": status,
            "matchedStrongTerms": strong_matches,
            "matchedBroadTerms": broad_matches,
            "validationStatus": "PENDING"
        })

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("Total candidates:", len(results))
    print("Offline review results:")
    for status, count in Counter(
        x["offlineReviewStatus"] for x in results
    ).items():
        print(status, ":", count)

    print("Saved:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
