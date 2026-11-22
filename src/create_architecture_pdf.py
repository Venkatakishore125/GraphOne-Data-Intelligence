from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "architecture.pdf"


def build():
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=letter,
                            rightMargin=0.55 * inch, leftMargin=0.55 * inch,
                            topMargin=0.55 * inch, bottomMargin=0.55 * inch)
    story = [
        Paragraph("GraphOne Data Intelligence — Architecture", styles["Title"]),
        Spacer(1, 10),
        Paragraph("1. Overall system architecture", styles["Heading2"]),
        Paragraph(
            "Collectors write JSON/CSV records through a normalization and validation layer. "
            "Product verification, startup, research-paper, news, and jobs pipelines share common "
            "source provenance, timestamps, deduplication, URL validation, and audit logging.",
            styles["BodyText"]),
        Paragraph("2. Scale to 500,000+ records", styles["Heading2"]),
        Paragraph(
            "Use partitioned object storage for raw snapshots, PostgreSQL or Parquet partitions for "
            "structured records, Redis for hot deduplication and request throttling, Kafka or RabbitMQ "
            "for ingestion queues, and worker pools for verification. Partition keys include source, "
            "publication date, country, or entity; batch writes and incremental checkpoints prevent reruns.",
            styles["BodyText"]),
        Paragraph("3. Storage choices", styles["Heading2"]),
        Paragraph(
            "PostgreSQL stores normalized records and provenance. A vector database such as pgvector or "
            "Qdrant stores embedding vectors for semantic search and near-duplicate review. A graph database "
            "such as Neo4j or Amazon Neptune stores company, product, paper, and source relationships.",
            styles["BodyText"]),
        PageBreak(),
        Paragraph("4. Entity resolution and deduplication", styles["Heading2"]),
        Paragraph(
            "Names are Unicode-normalized and exact canonical matches are separated from near matches. "
            "Domains and canonical URLs supplement name comparison. Low-confidence matches remain review-only "
            "and are never silently merged.",
            styles["BodyText"]),
        Paragraph("5. Freshness and 24-hour monitoring", styles["Heading2"]),
        Paragraph(
            "RSS/API collectors run on a scheduled interval. Publication dates are normalized to UTC, "
            "news and jobs are filtered to the last 24 hours, duplicates are removed by canonical URL, "
            "and source errors are retained in separate error logs.",
            styles["BodyText"]),
        Paragraph("6. LLM fallback", styles["Heading2"]),
        Paragraph(
            "LLM requests use Gemini Flash, then Groq Llama 3, then DeepSeek. HTTP 413 responses trigger "
            "text chunking and HTTP 429 responses trigger exponential backoff with random jitter. "
            "API keys come only from environment variables.",
            styles["BodyText"]),
        PageBreak(),
        Paragraph("7. Crawling and error handling", styles["Heading2"]),
        Paragraph(
            "Asynchronous crawling uses bounded concurrency, timeouts, retries, and robots.txt checks. "
            "The pipeline does not bypass Cloudflare, DataDome, CAPTCHA, authentication, or rate limits."
            "Protected pages are recorded as blocked or incomplete and never fabricated.",
            styles["BodyText"]),
        Paragraph("8. Deployment", styles["Heading2"]),
        Paragraph(
            "Stateless workers run from containers; schedules trigger incremental jobs; durable object "
            "storage retains raw evidence; monitoring tracks source availability, latency, deduplicated "
            "record counts, and data freshness. Secrets are injected at runtime.",
            styles["BodyText"]),
        Paragraph("9. Traceability", styles["Heading2"]),
        Paragraph(
            "Every exported record retains source URLs and collection timestamps. CSV deliverables correspond "
            "to Startups, Products, Research Papers, Jobs, News, and Entity Mapping Log tabs.",
            styles["BodyText"]),
    ]
    doc.build(story)
    return OUTPUT


if __name__ == "__main__":
    print(build())
