import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llm.text_chunker import chunk_text
from llm.llm_orchestrator import LLMFallback
from scrapers.news_monitor import NEWS_SOURCES, canonical_url as news_canonical_url
from scrapers.job_monitor import JOB_SOURCES, canonical_url as job_canonical_url
import requests
from entity_resolution.resolver import normalize_name, resolve_entities


def test_core_verified_product_dataset():
    rows = json.loads((ROOT / "data/products_1000_verified.json").read_text(encoding="utf-8-sig"))
    assert len(rows) == 1000
    names = {normalize_name(r["content"]["productName"]) for r in rows}
    domains = {(r["content"]["website"] or "").lower().replace("http://", "").replace("https://", "").split("/")[0].removeprefix("www.") for r in rows}
    assert len(names) == 1000
    assert len(domains) == 1000


def test_startups_and_papers():
    startups = json.loads((ROOT / "data/startups.json").read_text(encoding="utf-8-sig"))
    papers = json.loads((ROOT / "data/research_papers_enriched.json").read_text(encoding="utf-8-sig"))
    assert len(startups) == 1000
    assert len(papers) == 1000
    assert len({normalize_name(r["startup_name"]) for r in startups}) == 1000
    assert len({normalize_name(r["title"]) for r in papers}) == 1000
    assert all(r.get("source_url") for r in startups)
    assert all(r.get("paper_url") for r in papers)


def test_text_chunker():
    text = "abcdefghij" * 300
    chunks = chunk_text(text, max_chars=1000, overlap=100)
    assert chunks
    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert len("".join(chunks)) >= len(text)


def test_entity_resolution_is_deterministic():
    records = [{"name": "Open AI", "url": "https://openai.com"}]
    first = resolve_entities(records, "name", "url", "Test")
    second = resolve_entities(records, "name", "url", "Test")
    assert first == second
    assert len(first) == 1


def test_export_csv_templates_exist_after_pipeline():
    deliverables = ROOT / "deliverables"
    assert deliverables.exists()
    for name in ("startups.csv", "products.csv", "research_papers.csv",
                 "jobs.csv", "news.csv", "entity_mapping_log.csv"):
        assert (deliverables / name).exists()


def test_llm_fallback_order_is_gemini_groq_deepseek():
    llm = LLMFallback(max_chunk_chars=100)
    llm._gemini = lambda prompt: (_ for _ in ()).throw(RuntimeError("gemini unavailable"))
    llm._groq = lambda prompt: "groq result"
    llm._deepseek = lambda prompt: "deepseek result"
    result = llm.generate("short prompt")
    assert result["success"]
    assert result["provider"] == "groq"
    assert [event["provider"] for event in result["events"] if event["status"] == "failure"] == ["gemini"]
    assert any(event["provider"] == "groq" and event["status"] == "success" for event in result["events"])


def test_llm_loads_provider_keys_from_dotenv(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=test-only-value\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    LLMFallback()

    assert os.environ["GEMINI_API_KEY"] == "test-only-value"


def test_llm_413_triggers_chunking(monkeypatch):
    llm = LLMFallback(max_chunk_chars=400)
    response = requests.Response()
    response.status_code = 413
    attempted_lengths = []

    def gemini_chunked(prompt):
        attempted_lengths.append(len(prompt))
        if len(prompt) > 200:
            raise requests.HTTPError("413", response=response)
        return "chunk result"

    llm._gemini = gemini_chunked
    llm._groq = lambda prompt: "groq fallback"
    llm._deepseek = lambda prompt: "deepseek fallback"
    result = llm.generate("x" * 220)
    assert result["success"]
    assert result["provider"] == "gemini"
    assert attempted_lengths[0] == 220
    assert all(length <= 200 for length in attempted_lengths[1:])
    assert any(event["status"] == "chunked" for event in result["events"])


def test_llm_429_uses_backoff_before_fallback(monkeypatch):
    llm = LLMFallback(max_chunk_chars=100)
    response = requests.Response()
    response.status_code = 429

    def gemini_429(prompt):
        raise requests.HTTPError("429", response=response)

    llm._gemini = gemini_429
    llm._groq = lambda prompt: "groq fallback"
    llm._deepseek = lambda prompt: "deepseek fallback"
    sleeps = []
    monkeypatch.setattr("src.llm.llm_orchestrator.time.sleep", sleeps.append)
    monkeypatch.setattr("src.llm.llm_orchestrator.random.uniform", lambda lower, upper: 0.25)
    result = llm.generate("short prompt")
    assert result["success"]
    assert sleeps == [1.25, 2.25, 4.25]


def test_monitor_source_coverage_and_canonical_deduplication():
    assert len(NEWS_SOURCES) >= 5
    assert len(JOB_SOURCES) >= 5
    assert news_canonical_url("https://example.com/story/?utm_source=rss&x=1") == "https://example.com/story?x=1"
    assert job_canonical_url("https://example.com/job/?gclid=abc") == "https://example.com/job"
