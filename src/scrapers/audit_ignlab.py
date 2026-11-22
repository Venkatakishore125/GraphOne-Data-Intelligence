
import json
import re
from pathlib import Path
from collections import Counter

BASE_DIR = Path(__file__).resolve().parents[2]
INPUT_FILE = BASE_DIR / "data" / "ignlab_raw.json"

with open(INPUT_FILE, encoding="utf-8") as f:
    listings = json.load(f)

AI_PATTERN = re.compile(
    r"\b(ai|artificial intelligence|machine learning|"
    r"deep learning|llm|generative ai|chatbot|"
    r"computer vision|natural language processing|"
    r"automation|ai agent|copilot|rag)\b",
    re.IGNORECASE
)

matches = []

for item in listings:
    tags = item.get("tags", [])
    if isinstance(tags, list):
        tags_text = " ".join(
            str(t.get("name", "")) if isinstance(t, dict) else str(t)
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

    if AI_PATTERN.search(searchable):
        matches.append(item)

valid_urls = [
    item for item in matches
    if str(item.get("url", "")).startswith(("https://", "http://"))
]

print("Total raw listings:", len(listings))
print("AI keyword matches:", len(matches))
print("AI matches with website URLs:", len(valid_urls))
print("AI matches without website URLs:", len(matches) - len(valid_urls))
print("\nCategories:")
print(Counter(str(x.get("category", "Unknown")) for x in matches))
print("\nSample AI matches:")

for item in matches[:10]:
    print("-", item.get("name"), "|", item.get("url"))
