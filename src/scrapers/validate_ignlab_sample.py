
import json
import requests
import time
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parents[2]
INPUT_FILE = BASE_DIR / "data" / "ignlab_new_candidates.json"

with open(INPUT_FILE, encoding="utf-8") as f:
    candidates = json.load(f)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; GraphOneResearch/1.0)"
})

sample = candidates[:20]

accessible = 0
failed = 0

for item in sample:
    url = item.get("website", "")

    try:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            print("INVALID:", item["productName"])
            failed += 1
            continue

        response = session.get(
            url,
            timeout=12,
            allow_redirects=True,
            stream=True
        )

        if response.status_code < 400:
            print("ACCESSIBLE:", item["productName"], response.status_code)
            accessible += 1
        else:
            print("HTTP ERROR:", item["productName"], response.status_code)
            failed += 1

        response.close()
        time.sleep(1)

    except requests.RequestException as error:
        print("REQUEST FAILED:", item["productName"], str(error)[:100])
        failed += 1

print("\nSample size:", len(sample))
print("Accessible:", accessible)
print("Failed:", failed)
