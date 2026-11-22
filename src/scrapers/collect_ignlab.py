
import json
import time
import random
import requests
from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"

API_URL = "https://launch.ignlab.net/api/v1/listings"
RAW_FILE = DATA_DIR / "ignlab_raw.json"
CHECKPOINT_FILE = DATA_DIR / "ignlab_checkpoint.json"

LIMIT = 30
REQUEST_DELAY = 5
MAX_RETRIES = 5

session = requests.Session()
session.headers.update({
    "User-Agent": "GraphOne-Data-Intelligence/1.0",
    "Accept": "application/json"
})


def save_json(path, data):
    temp = path.with_suffix(".tmp")

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    temp.replace(path)


def load_progress():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Create checkpoint before making the first API request.
    if not CHECKPOINT_FILE.exists():
        save_json(CHECKPOINT_FILE, {
            "next_offset": 0,
            "total": None,
            "completed": False
        })

    checkpoint = json.load(open(CHECKPOINT_FILE, encoding="utf-8"))

    if RAW_FILE.exists():
        listings = json.load(open(RAW_FILE, encoding="utf-8"))
    else:
        listings = []
        save_json(RAW_FILE, listings)

    return listings, checkpoint


def get_wait_time(response, attempt):
    retry_after = response.headers.get("Retry-After")

    if retry_after:
        try:
            return max(1, float(retry_after))
        except ValueError:
            try:
                retry_date = parsedate_to_datetime(retry_after)
                return max(
                    1,
                    (retry_date - datetime.now(timezone.utc)).total_seconds()
                )
            except (TypeError, ValueError):
                pass

    return min(120 * (2 ** attempt), 1800) + random.uniform(5, 20)


def fetch_page(offset):
    for attempt in range(MAX_RETRIES):
        try:
            response = session.get(
                API_URL,
                params={"offset": offset, "limit": LIMIT},
                timeout=45
            )

            if response.status_code == 429:
                wait = get_wait_time(response, attempt)
                print(f"HTTP 429. Waiting {wait:.0f} seconds.")
                time.sleep(wait)
                continue

            response.raise_for_status()
            data = response.json()

            if not isinstance(data, dict):
                raise ValueError("Unexpected API response format")

            if not isinstance(data.get("listings"), list):
                raise ValueError("Missing listings array")

            return data

        except (requests.RequestException, ValueError) as error:
            wait = min(60 * (2 ** attempt), 900)
            print("Request error:", error)
            print(f"Retrying in {wait} seconds.")
            time.sleep(wait)

    raise RuntimeError(
        f"Unable to fetch offset {offset}. "
        "Checkpoint remains available for a later retry."
    )


def main():
    listings, checkpoint = load_progress()

    if checkpoint.get("completed"):
        print("Download already completed.")
        print("Total raw listings:", len(listings))
        return

    offset = checkpoint.get("next_offset", 0)

    print("Existing saved listings:", len(listings))
    print("Resuming from offset:", offset)

    while True:
        data = fetch_page(offset)
        page = data["listings"]

        if not page:
            checkpoint["completed"] = True
            save_json(CHECKPOINT_FILE, checkpoint)
            break

        # Preserve the API records as received.
        listings.extend(page)

        offset += len(page)

        checkpoint.update({
            "next_offset": offset,
            "total": data.get("total"),
            "completed": offset >= data.get("total", offset)
        })

        # Save both files after every successful page.
        save_json(RAW_FILE, listings)
        save_json(CHECKPOINT_FILE, checkpoint)

        print(
            f"Saved {len(listings)} / {checkpoint['total']} listings"
        )

        if checkpoint["completed"]:
            break

        time.sleep(REQUEST_DELAY)

    print("\nIgnlab collection finished.")
    print("Raw listings:", len(listings))
    print("Raw data:", RAW_FILE)
    print("Checkpoint:", CHECKPOINT_FILE)


if __name__ == "__main__":
    main()
