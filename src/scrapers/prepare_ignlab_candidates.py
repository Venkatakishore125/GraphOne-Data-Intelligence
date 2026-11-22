
import json
import re
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"

INPUT_FILE = DATA_DIR / "ignlab_raw.json"
OUTPUT_FILE = DATA_DIR / "ignlab_ai_candidates.json"

AI_PATTERN = re.compile(
    r"\b(ai|artificial intelligence|machine learning|"
    r"deep learning|llm|generative ai|chatbot|"
    r"computer vision|natural language processing|"
    r"copilot|retrieval augmented generation|rag|"
    r"ai agent)\b",
    re.IGNORECASE
)


def valid_url(value):
    try:
        parsed = urlparse(str(value or ""))
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except ValueError:
        return False


def main():
    with open(INPUT_FILE, encoding="utf-8") as f:
        listings = json.load(f)

    candidates = []
    seen = set()

    for item in listings:
        tags = item.get("tags", [])

        if isinstance(tags, list):
            tags_text = " ".join(
                str(t.get("name", "")) if isinstance(t, dict)
                else str(t)
                for t in tags
            )
        else:
            tags_text = str(tags or "")

        searchable = " ".join([
            str(item.get("name") or ""),
            str(item.get("description") or ""),
            str(item.get("category") or ""),
            tags_text
        ])

        if not AI_PATTERN.search(searchable):
            continue

        name = str(item.get("name") or "").strip()
        website = str(item.get("url") or "").strip()

        if not name or not valid_url(website):
            continue

        key = (name.lower(), website.lower())

        if key in seen:
            continue

        seen.add(key)

        candidates.append({
            "productName": name,
            "website": website,
            "description": item.get("description"),
            "category": item.get("category"),
            "tags": tags,
            "pricing": item.get("pricing"),
            "sourceName": "Ignlab",
            "sourceUrl": "https://launch.ignlab.net/",
            "validationStatus": "PENDING"
        })

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(candidates, f, indent=2, ensure_ascii=False)

    print("Raw listings:", len(listings))
    print("AI candidate records:", len(candidates))
    print("Saved to:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
