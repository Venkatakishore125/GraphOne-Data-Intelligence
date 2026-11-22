# 🚀 GraphOne Data Intelligence

An AI-powered data intelligence platform for discovering, collecting, monitoring, and organizing information about AI startups, products, research papers, news, and jobs.

> **Assessment project** — built to demonstrate data collection, data quality, entity resolution, LLM orchestration, and scalable crawling patterns.

## ✨ Project Overview

GraphOne Data Intelligence brings multiple information sources into a consistent data pipeline. It is designed to collect source-attributed records, normalize and deduplicate them, monitor recent updates, and prepare structured outputs for analysis.

## 🧩 Core Capabilities

- **AI ecosystem discovery** — structured catalogs of AI startups, products, and research papers.
- **News monitoring** — configurable public sources with a rolling 24-hour publication window.
- **Job monitoring** — configurable public job-board/API collection with date normalization and deduplication.
- **LLM orchestration** — provider fallback design for Gemini Flash, Groq Llama, and DeepSeek.
- **Entity resolution** — deterministic matching against canonical seed entities with an audit log.
- **Asynchronous crawling** — concurrent collection with timeouts, retries, and respect for site access rules.
- **Deliverable generation** — CSV exports, a six-tab Excel workbook, and architecture documentation.

## 🏗️ Architecture at a Glance

```text
Public Sources
  ├── Startup / Product Directories
  ├── Research Paper Sources
  ├── AI News Feeds
  └── Job APIs / Boards
          │
          ▼
Collection & Crawling
          │
          ▼
Parsing • Date Normalization • URL Validation
          │
          ▼
Deduplication & Entity Resolution
          │
          ▼
Structured Data (JSON / CSV)
          │
          ├── LLM Provider Orchestration
          ├── Six-tab Excel Workbook
          └── Architecture & Completion Reports
```

## 📂 Repository Structure

The checked-in project layout is:

```text
GraphOne-Data-Intelligence/
├── data/             # Collected and validated datasets
├── deliverables/     # CSV exports and assessment outputs
├── src/              # Scrapers, pipeline, LLM, and utilities
├── tests/            # Automated tests
├── architecture.pdf  # System architecture (maximum 3 pages)
├── README.md
├── requirements.txt
├── .env.example      # Placeholder environment variables only
└── FINAL_ASSESSMENT_COMPLETION_REPORT.md
```

The `data/` directory also retains source snapshots and manual-review artifacts used during
collection. `deliverables/` contains the six CSV files corresponding to the six workbook tabs.

## ⚙️ Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/Venkatakishore125/GraphOne-Data-Intelligence.git
cd GraphOne-Data-Intelligence
```

### 2. Create and activate a virtual environment

**Windows PowerShell**

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Configure environment variables

Copy `.env.example` to `.env` and add your own provider keys if needed. Keep `.env` private; never commit API keys, passwords, or access tokens.

### 5. Run the pipeline

Run the primary collection and export workflow from the repository root:

```powershell
python src\main.py
```

Generate the architecture PDF and Excel workbook with:

```powershell
python src\create_architecture_pdf.py
python src\create_xlsx_deliverable.py
```

## 📊 Assessment Deliverables

The local assessment package is intended to include:

| Deliverable | Description |
|---|---|
| Startups | Structured AI startup dataset |
| Products | Structured AI product catalog |
| Research Papers | Research paper metadata and source links |
| News | Recent AI news records |
| Jobs | Recent AI job records |
| Entity Mapping Log | Canonical entity-resolution decisions |
| Excel Workbook | Six tabs covering the above datasets |
| Architecture PDF | System design and scaling approach |
| [Completion Report](FINAL_ASSESSMENT_COMPLETION_REPORT.md) | Requirement-by-requirement status and validation |

The bundled package also includes:

- [Architecture PDF](architecture.pdf)
- [Six-tab Excel workbook](GraphOne_Assessment_Deliverables.xlsx)
- [Six CSV deliverables](deliverables/)
- [Entity-resolution and collection data](data/)

The latest recorded local snapshot contains 1,000 startups, 1,000 verified products,
1,000 enriched research papers, 3 eligible news records, and 184 eligible job records.
Counts from later monitoring runs may change as source activity changes.

## ✅ Data Quality & Responsible Collection

- Preserve a source URL for each collected record.
- Normalize dates to a consistent timezone before applying freshness filters.
- Deduplicate using canonical URLs and stable entity identifiers where available.
- Keep rejected and manual-review records separate from verified datasets.
- Respect robots.txt, source terms, rate limits, and access controls.
- Do not bypass anti-bot protections or access restricted content without permission.
- Report actual collection counts; never fabricate records to satisfy a target.

## 🧪 Testing

Run the project's test suite from the repository root:

```bash
python -m pytest -q
```

Also compile-check source modules where applicable:

```bash
python -m compileall -q src tests
```

Test results should be refreshed against the exact commit being submitted.

## 🔐 Security

- `.env`, virtual environments, caches, and local secrets should be excluded by `.gitignore`.
- Use `.env.example` only for variable names and placeholder values.
- Review staged files before committing.
- Rotate any credential accidentally published to a public repository.

## 📌 Current Publication Status

The repository includes the project source, data snapshots, tests, six CSV deliverables,
Excel workbook, architecture PDF, and completion report. Source availability and rolling
news/job counts can change on subsequent runs.

## 📄 License

No license has been selected yet. Until a license is added, all rights remain with the respective copyright holders; do not assume the code is available for reuse.
