import csv
import json
from pathlib import Path
from urllib.parse import urlsplit


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def startup_rows(root: Path) -> list[dict]:
    data = read_json(root / "data/startups.json")
    return [{
        "startupName": r.get("startup_name"),
        "website": r.get("website"),
        "description": r.get("description"),
        "industry": r.get("industry"),
        "subindustry": r.get("subindustry"),
        "location": r.get("location"),
        "sourceUrl": r.get("source_url"),
        "collectedAt": r.get("collected_at"),
    } for r in data]


def product_rows(root: Path) -> list[dict]:
    data = read_json(root / "data/products_1000_verified.json")
    result = []
    for r in data:
        c = r.get("content") or {}
        s = r.get("source") or {}
        result.append({
            "recordId": r.get("recordId"),
            "productName": c.get("productName"),
            "website": c.get("website"),
            "description": c.get("description"),
            "category": c.get("category"),
            "pricingModel": c.get("pricingModel"),
            "sourceName": s.get("name"),
            "sourceUrl": s.get("url"),
            "collectedAt": r.get("collectedAt"),
        })
    return result


def paper_rows(root: Path) -> list[dict]:
    data = read_json(root / "data/research_papers_enriched.json")
    return [{
        "title": r.get("title"),
        "authors": "; ".join(r.get("authors") or []),
        "paperUrl": r.get("paper_url"),
        "publishedDate": r.get("published_date"),
        "githubUrl": r.get("github_url"),
        "githubStars": r.get("github_stars"),
    } for r in data]


def write_csv(path: Path, rows: list[dict]):
    fields = list(rows[0].keys()) if rows else []
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def export_six_tabs(root: Path) -> dict[str, Path]:
    out = root / "deliverables"
    out.mkdir(parents=True, exist_ok=True)
    exports = {
        "Startups": startup_rows(root),
        "Products": product_rows(root),
        "Research Papers": paper_rows(root),
        "Jobs": read_json(root / "data/jobs_last_24h.json") if (root / "data/jobs_last_24h.json").exists() else [],
        "News": read_json(root / "data/news_last_24h.json") if (root / "data/news_last_24h.json").exists() else [],
    }
    entity_path = root / "data/entity_mapping_log.csv"
    if entity_path.exists():
        with entity_path.open(encoding="utf-8-sig", newline="") as stream:
            exports["Entity Mapping Log"] = list(csv.DictReader(stream))
    else:
        exports["Entity Mapping Log"] = []

    result = {}
    for sheet_name, rows in exports.items():
        filename = sheet_name.lower().replace(" ", "_") + ".csv"
        path = out / filename
        write_csv(path, rows)
        result[sheet_name] = path
    return result
