
import json
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"

CANDIDATES_FILE = DATA_DIR / "ignlab_ai_candidates.json"
PRODUCTS_FILE = DATA_DIR / "products.json"
OUTPUT_FILE = DATA_DIR / "ignlab_new_candidates.json"


def normalize_url(url):
    parsed = urlparse(str(url or "").strip().lower())
    return parsed.netloc.removeprefix("www.")


def main():
    with open(CANDIDATES_FILE, encoding="utf-8") as f:
        candidates = json.load(f)

    with open(PRODUCTS_FILE, encoding="utf-8") as f:
        existing = json.load(f)

    existing_domains = {
        normalize_url(p.get("content", {}).get("website"))
        for p in existing
    }

    existing_domains.discard("")

    new_candidates = []
    already_present = []

    for candidate in candidates:
        domain = normalize_url(candidate.get("website"))

        if not domain:
            continue

        if domain in existing_domains:
            already_present.append(candidate)
        else:
            new_candidates.append(candidate)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(new_candidates, f, indent=2, ensure_ascii=False)

    print("Existing products:", len(existing))
    print("Ignlab candidates:", len(candidates))
    print("Already present:", len(already_present))
    print("Potential new candidates:", len(new_candidates))
    print("Saved:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
