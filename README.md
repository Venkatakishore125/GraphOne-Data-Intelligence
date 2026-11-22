# GraphOne Data Intelligence

**A traceable data pipeline for discovering and monitoring AI companies, products, research, news, and jobs.**

[Architecture PDF](architecture.pdf) · [Assessment workbook](GraphOne_Assessment_Deliverables.xlsx) · [Completion report](FINAL_ASSESSMENT_COMPLETION_REPORT.md)

## Overview

GraphOne consolidates source-attributed AI ecosystem datasets and practical collection, review, entity-resolution, and export utilities. The project keeps source URLs and timestamps where available, retains verification evidence, normalizes monitoring dates to UTC, and prepares six CSV exports plus an Excel workbook.

This is an assessment and research project, not a hosted or continuously running service. Its local snapshots and rolling news/job results describe the latest captured run; new runs may have different counts.

## Features

- **Reference datasets:** startup, verified product, and research-paper collections with source links.
- **News monitoring:** seven public RSS feeds; canonical URL deduplication and a rolling 24-hour publication window.
- **Job monitoring:** five public APIs; AI relevance filtering, UTC date normalization, and canonical URL deduplication.
- **Entity resolution:** deterministic matching against canonical seed entities with an auditable decision log.
- **LLM fallback module:** Gemini, Groq, and DeepSeek provider order, chunking for HTTP 413, and retry backoff for HTTP 429. Provider calls require credentials and have not been live-tested for this snapshot.
- **Responsible retrieval:** asynchronous crawler utilities and article retrieval observe robots rules, timeouts, and source access restrictions.
- **Assessment exports:** six CSV deliverables, a six-tab workbook, an architecture document, and validation report.

## Technology

- Python 3.10+
- HTTP/RSS and parsing: `requests`, `aiohttp`, `feedparser`, `beautifulsoup4`
- Data and matching: Python JSON/CSV, `rapidfuzz`
- LLM configuration: `python-dotenv`, provider-compatible HTTP APIs
- Deliverables: `xlsxwriter`, `openpyxl`, `reportlab`, `pypdf`
- Tests: `pytest`

## Architecture

```text
Public datasets, feeds, and job APIs
                 │
                 ▼
       Collection and parsing
                 │
       ┌─────────┴─────────┐
       ▼                   ▼
 UTC date filtering   Robots/access checks
       │                   │
       └─────────┬─────────┘
                 ▼
     JSON snapshots and evidence
                 │
        Entity resolution log
                 │
      Six CSVs → six-tab workbook
```

The runnable workflow is in `src/main.py`. The architecture PDF also describes a proposed scale-out design; database, queue, and graph-storage services in that design are not deployed by this project.

## Installation

Requirements: Python 3.10 or later. Internet access is needed for live feed/API collection.

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Environment configuration

Copy `.env.example` to `.env`, then add keys only for providers you are authorized to use:

```powershell
Copy-Item .env.example .env
```

On macOS or Linux, use `cp .env.example .env`. The file contains:

```dotenv
GEMINI_API_KEY=
GROQ_API_KEY=
DEEPSEEK_API_KEY=
```

Keys are optional for the collection and export workflow. `LLMFallback` reads `.env` from the current project directory when initialized. The checked-in example contains empty values; `.env` and credentials are excluded by [.gitignore](.gitignore). Never commit provider keys, passwords, access tokens, or private certificates.

## Run the project

From the repository root, run the collection, entity mapping, and CSV export workflow:

```powershell
python src\main.py
```

Generate the other deliverables:

```powershell
python src\create_architecture_pdf.py
python src\create_xlsx_deliverable.py
```

The pipeline uses public sources and may update rolling snapshots. Network failures are written to `data/news_last_24h_errors.json` and `data/jobs_last_24h_errors.json`; records are not fabricated to meet target counts.

## Repository layout

```text
GraphOne-Data-Intelligence/
├── data/                 # Datasets, monitoring snapshots, evidence, and review history
├── deliverables/         # Six import-ready CSV exports
├── src/
│   ├── entity_resolution/
│   ├── llm/
│   ├── scrapers/
│   ├── create_architecture_pdf.py
│   ├── create_xlsx_deliverable.py
│   ├── export_deliverables.py
│   └── main.py
├── tests/
├── .env.example
├── .gitignore
├── architecture.pdf
├── GraphOne_Assessment_Deliverables.xlsx
├── FINAL_ASSESSMENT_COMPLETION_REPORT.md
├── README.md
└── requirements.txt
```

The `data/` directory also contains useful source snapshots, evidence, rejected records, and manual-review history; these are retained for traceability.

## Dataset snapshot

Latest checked local snapshot: **November 22, 2026** (news/job snapshots captured around 14:01 local time). Counts are run-specific.

| Dataset | Records | Validation |
|---|---:|---|
| Startups | 1,000 | Unique normalized names; source URLs present |
| Verified AI products | 1,000 | Unique product names and website domains |
| Research papers | 1,000 | Unique titles; paper URLs present |
| News, rolling 24-hour window | 3 | The Verge AI; unique URLs |
| Jobs, rolling 24-hour window | 184 | 101 Arbeitnow, 12 Himalayas, 71 Jobicy; unique URLs |
| Entity mapping log | 3,000 | Startup, product, and research records |

News/job published timestamps were checked against each record's collection time and the 24-hour window. Source URLs were syntactically checked; this does not guarantee that each external website remains reachable.

## Assessment deliverables

The Excel workbook has exactly six tabs, with matching CSV exports:

| Tab | CSV |
|---|---|
| Startups | [startups.csv](deliverables/startups.csv) |
| Products | [products.csv](deliverables/products.csv) |
| Research Papers | [research_papers.csv](deliverables/research_papers.csv) |
| Jobs | [jobs.csv](deliverables/jobs.csv) |
| News | [news.csv](deliverables/news.csv) |
| Entity Mapping Log | [entity_mapping_log.csv](deliverables/entity_mapping_log.csv) |

Also included: [Excel workbook](GraphOne_Assessment_Deliverables.xlsx), [architecture PDF](architecture.pdf), [completion report](FINAL_ASSESSMENT_COMPLETION_REPORT.md), and [product verification evidence](data/products_1000_verification_evidence.json).

## Tests and validation

```powershell
python -m compileall -q src tests
python -m pytest -q
```

The automated tests cover core dataset counts, text chunking, entity resolution, exports, `.env` configuration, provider fallback behavior, HTTP 413 chunking, HTTP 429 retry delays, and monitoring source/canonical URL behavior. The [completion report](FINAL_ASSESSMENT_COMPLETION_REPORT.md) records the latest validation results.

## Security and responsible collection

- `.env`, virtual environments, caches, key files, and credential files are ignored by Git.
- `.env.example` contains variable names with empty placeholders only.
- Respect source terms, robots.txt rules, rate limits, and access controls; do not bypass anti-bot or authentication systems.
- Keep provider credentials local and rotate any credential that is accidentally published.

## Limitations and publication status

- News and jobs are rolling snapshots, not a continuously scheduled service.
- Feed/API availability, publication times, and article text vary by source; retrieval may be limited to a source summary.
- Gemini, Groq, and DeepSeek calls are implemented but require configured keys; no live provider call is claimed as tested.
- The database/storage module is not implemented; persistent database storage is not part of the current workflow.
- Google Sheets has not been published. The workbook and CSVs are ready for import.
- The project is published at [github.com/Venkatakishore125/GraphOne-Data-Intelligence](https://github.com/Venkatakishore125/GraphOne-Data-Intelligence).
- No license has been selected; no reuse rights should be assumed.
