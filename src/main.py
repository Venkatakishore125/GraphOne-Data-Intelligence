import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "src"))

from entity_resolution.resolver import resolve_entities
from export_deliverables import export_six_tabs
from scrapers.job_monitor import collect_jobs, JOB_SOURCES
from scrapers.news_monitor import collect_news, NEWS_SOURCES


def normalize_name(value):
    import re
    import unicodedata
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(c for c in text if c.isalnum())


def write_entity_mapping_log():
    startups = json.loads((DATA / "startups.json").read_text(encoding="utf-8-sig"))
    products = json.loads((DATA / "products_1000_verified.json").read_text(encoding="utf-8-sig"))
    papers = json.loads((DATA / "research_papers_enriched.json").read_text(encoding="utf-8-sig"))

    rows = []
    rows.extend(resolve_entities(startups, "startup_name", "source_url", "Startups"))
    rows.extend(resolve_entities(
        [{"productName": r["content"].get("productName"), "sourceUrl": r["content"].get("website")} for r in products],
        "productName", "sourceUrl", "Products"))
    rows.extend(resolve_entities(
        [{"title": r.get("title"), "paperUrl": r.get("paper_url")} for r in papers],
        "title", "paperUrl", "Research Papers"))

    path = DATA / "entity_mapping_log.csv"
    fields = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def validate_core_counts():
    startups = json.loads((DATA / "startups.json").read_text(encoding="utf-8-sig"))
    products = json.loads((DATA / "products_1000_verified.json").read_text(encoding="utf-8-sig"))
    papers = json.loads((DATA / "research_papers_enriched.json").read_text(encoding="utf-8-sig"))

    startup_names = [normalize_name(r.get("startup_name")) for r in startups]
    product_names = [normalize_name(r["content"].get("productName")) for r in products]
    paper_names = [normalize_name(r.get("title")) for r in papers]
    return {
        "startups": len(startups),
        "uniqueStartups": len(set(startup_names)),
        "products": len(products),
        "uniqueProducts": len(set(product_names)),
        "papers": len(papers),
        "uniquePapers": len(set(paper_names)),
    }


def main():
    print("Running GraphOne assessment pipeline...")
    news, news_errors = collect_news(output_dir=DATA)
    jobs, jobs_errors = collect_jobs(output_dir=DATA)
    mapping = write_entity_mapping_log()
    exports = export_six_tabs(ROOT)
    core = validate_core_counts()
    print(json.dumps({
        "core": core,
        "news24h": len(news),
        "newsSources": len(NEWS_SOURCES),
        "newsErrors": len(news_errors),
        "jobs24h": len(jobs),
        "jobSources": len(JOB_SOURCES),
        "jobErrors": len(jobs_errors),
        "entityMappings": len(mapping),
        "exports": {name: str(path) for name, path in exports.items()},
    }, indent=2))


if __name__ == "__main__":
    main()