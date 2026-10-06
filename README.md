# E-Commerce Analytics Intelligence System

An automated system that monitors business metrics, detects unusual patterns, and helps explain what's driving changes in the data.

## Project Overview

This project analyses real UK retail transaction data to automatically:
- Calculate and track 16 business metrics (revenue, orders, customer behaviour, etc.)
- Detect when metrics behave unusually using statistical methods
- Figure out which customer segments or products are driving changes
- Provide actionable explanations instead of just numbers

**Why I built this:** I wanted to go beyond basic data analysis notebooks and build something that could actually run in production. Most analytics work involves repetitive calculations and manual investigation - this automates that process. Plus, I was curious about how companies like Amplitude or Mixpanel structure their metric systems under the hood.

## Current Status

**Phase:** Phase 7.5 Complete  
**Progress:** Full pipeline from raw data to AI-generated narratives, live dashboard, LLM observability, PostgreSQL migration, dbt transformation layer, Power BI reporting layer, GitHub Actions CI/CD - plus a full operational hardening pass that actually ran every layer end-to-end against live infrastructure and fixed what broke  
**Next Up:** Phase 8 - AWS deployment (EC2, RDS, S3), FastAPI layer, live public URL

### Completed:
- **Phase 1 - Foundation:** Project architecture and KPI specifications
- **Phase 2 - Data Pipeline:** Data ingestion and validation pipeline
  - Successfully loaded 541,909 transactions
  - Implemented 14 automated quality checks
  - Achieved 71.4% data quality score (10/14 checks passed)
  - Identified and documented 4 data anomalies
- **Phase 3 - KPI Engine:** KPI computation engine
  - Built config-driven formula parser that reads metric definitions from YAML
  - Implemented support for simple aggregations, cross-KPI dependencies, conditional filtering, and complex multi-step calculations
  - All 16 KPIs calculating correctly across Finance, Operations, Growth, Product, and International categories
  - Results saved with timestamps to `data/processed/kpi_results.csv`
- **Phase 4 - Anomaly Detection:** Statistical anomaly detection
  - Built detection engine running Z-score, IQR, and Mann-Kendall tests across all 14 KPIs
  - Implemented confidence scoring that boosts when multiple methods agree on the same anomaly
  - Added baseline windowing to exclude Christmas 2010 from baseline calculations - without this, the seasonal spike inflates "normal" and makes regular months look like drops
  - Detected 47 anomalies across 13 KPIs on the weekly time series
  - Notable finding: product_revenue_concentration spiked above expected in June 2011 - revenue was more concentrated in top 20 products than usual that week
  - Results saved to data/insights/anomalies.csv for root cause analysis
- **Phase 5 - Root Cause Analysis:** Automated dimensional slicing to explain anomalies
  - For each anomaly, filters raw transaction data to the anomaly week and slices by Country, StockCode, and HourOfDay
  - Calculates each segment's contribution to the total deviation, scaled against the baseline period
  - 19 anomalies successfully explained, 20 flagged for manual review (ratio KPIs cannot be directly segmented)
  - Ratio KPIs are flagged rather than producing misleading results - you cannot slice repeat_customer_rate by Country without recalculating numerator and denominator separately per segment, and doing it naively gives nonsense numbers
  - Results saved to data/insights/root_causes.csv
  - Notable finding: the November 2011 spike in active_customers, order_count, total_revenue, and units_sold all trace back to the same cause - UK customers buying two specific products (StockCode 23084 and 22086) at unusually high volumes during afternoon hours. That is not four separate anomalies, it is one pre-Christmas wholesale buying event showing up across four metrics.
- **Phase 6 - Dashboard, Narratives, and AI Layer:** Streamlit dashboard, LLM narrative generation, RAG pipeline, and AI observability
  - Built Streamlit dashboard with 5 pages: Overview, Time Series, Anomalies, Insights, AI Lab
  - Precompute layer saves all pipeline outputs to parquet cache for fast dashboard loading
  - LLM narratives generated via Groq (Llama 3.1-8b-instant) for all 19 explained anomalies
  - Prompt versioning system in `config/prompts.yaml` - v1 to v2 reduced quality violations from 42% to 0%
  - Monitoring layer logs every LLM call to JSONL with latency, token usage, cost, and quality flags
  - RAG pipeline built with LangChain LCEL + ChromaDB + sentence-transformers - retrieves 3 similar historical anomalies before generating each narrative
  - AI Lab dashboard page surfaces monitoring stats, narrative comparison (standard vs RAG), and full prompt version history
  - TenantConfig path resolution layer - single-tenant now, multi-tenant ready
- **Phase 7 - PostgreSQL + dbt + Power BI + CI/CD (Complete):**
  - Migrated all pipeline outputs from CSV/JSON/JSONL to PostgreSQL 15 running in Docker
  - Built dbt transformation layer with staging, intermediate, and mart model layers
  - Built 4-page Power BI report connected to the analytics schema via ODBC
  - GitHub Actions CI/CD pipeline running dbt compile and schema tests on every push, pytest on every PR
  - See Phase 7 section below for full details
- **Phase 7.5 - Operational Hardening (Complete):**
  - Ran a 4-domain code review (Python pipeline, RAG/LLM layer, dbt/SQL, security) and fixed every CRITICAL and HIGH finding: a transaction rollback bug in `migrate.py`, a division-by-zero in the dbt weekly model, SQL identifier injection hardening, a fail-closed database password, `tenant_id` path-traversal validation, and RAG retrieval quality
  - Then actually ran the whole pipeline end-to-end against live infrastructure instead of stopping at "the code looks right" - this surfaced a Windows console encoding crash, a fully deprecated LLM model, a stale network relay stealing the database port, an unrecoverable database password, and a silent data-duplication bug that static review had no way to catch
  - See "Phase 7.5: Operational Hardening" in the Development Plan section below for the full story

### Future Ideas (might add later):
- AWS deployment (EC2, RDS, S3) with FastAPI layer and live public URL
- Multi-tenant support for multiple business datasets
- Churn prediction model on the same dataset

Note: I'm prioritising getting each layer working well before moving to the next. Better to have 5 solid features than 8 half-baked ones.

---

## KPI Results (on 541,909 UK retail transactions)

| Metric | Value |
|---|---|
| Total Revenue | £9,747,747.93 |
| Revenue per Order | £376.36 |
| Revenue per Customer | £2,229.59 |
| Order Count | 25,900 |
| Items per Order | 200 |
| Units Sold | 5,176,450 |
| Active Customers | 4,372 |
| Repeat Customer Rate | ~70% |
| New Customers | 4,372 |
| Product Revenue Concentration | ~14% from top 20 products |
| Avg Unit Price | £1.88 |
| Product Return Rate | ~20% |
| International Revenue Share | ~16% |
| Weekend Revenue Share | ~8% |
| Peak Hour Concentration | ~40% |

---

## Data Quality Findings

Initial data quality assessment revealed some interesting characteristics:

**Overall Score: 71.4% (10/14 checks passed)**

**Passing Checks:**
- Schema validation: All columns present with correct types
- Completeness: CustomerID 24.9% missing (acceptable - represents guest checkouts)
- Completeness: Description 0.3% missing (well within threshold)
- Cancellations properly marked with negative quantities

**Known Issues (Documented, Not Fixed):**
- 2 transactions with negative unit prices (0.0004% of data)
- 2 transactions exceeding £100K threshold (0.0004% of data)

**Decision:** Proceeding with these anomalies documented rather than cleaned. In a real-world scenario, these would be flagged for business review - they could be legitimate bulk orders or data entry errors requiring domain expertise to resolve. This demonstrates that the validation system works as intended: it catches edge cases for human review rather than silently accepting everything.

---

## How It Works

The system has 7 layers that work together:

```
Data Layer
  v Loads and validates CSV data

KPI Layer
  v Calculates metrics from config files

Detection Layer
  v Finds anomalies and trends statistically

Analysis Layer
  v Figures out why metrics changed

AI Layer
  v Generates plain-English narratives with RAG context, logs every call

Output Layer
  v Presents findings through Streamlit dashboard

Database + Transformation Layer
  v PostgreSQL stores all outputs; dbt builds clean mart tables for reporting
```

**Config-Driven Design** - metrics defined in YAML, not Python. Business logic is separate from implementation. Inspired by how dbt handles metric definitions.

**How the formula parser works:** The KPI engine reads formula strings from `config/kpis.yaml` and executes them dynamically. It supports simple aggregations, cross-KPI references, conditional filtering, complex multi-step calculations, and customer groupby conditions.

---

## Phase 7: PostgreSQL + dbt + Power BI + CI/CD

### Architecture

Phase 7 replaces the flat-file outputs (CSV, JSON, JSONL) with a proper database layer, then adds a dbt transformation layer that computes the weekly KPI time series directly in SQL. The goal is a clean separation: Python loads raw data, dbt transforms it, Power BI reads from mart tables.

```
data/raw/UK retail data.csv
        v  scripts/migrate.py
PostgreSQL (public schema)
  raw_transactions  - 541,909 rows
  kpi_results       - 22 aggregate rows
  anomalies         - 46 detected anomalies
  root_causes       - 77 dimensional driver rows
  llm_calls         - 76 monitored LLM calls
  narratives        - 38 generated narratives
        v  dbt
analytics schema (dbt-managed)
  stg_transactions        - cleaned, filtered view (530,104 rows)
  int_weekly_transactions - weekly aggregates by country and product
  mart_weekly_kpis        - final weekly KPI time series (Power BI reads this)
  mart_anomaly_summary    - anomalies joined to top root cause driver (Power BI reads this)
        v  Power BI
4-page report
  Executive Overview    - weekly revenue trend + headline KPI cards
  Anomaly Monitor       - anomaly count by severity and KPI, anomaly detail table
  Root Cause Analysis   - average root cause contribution by KPI, driver detail table
  KPI Trends            - side-by-side weekly line charts for all 6 mart KPIs
```

### Why dbt

The Python KPI engine computes metrics in memory and saves aggregate totals to CSV - one row per pipeline run. That's fine for a script but it produces only 22 rows and can't be queried directly. dbt recomputes the same metrics in SQL, running inside Postgres, producing a proper 53-week time series that Power BI can connect to.

The other benefit is what dbt gives you for free: automated data tests, auto-generated documentation, and a visual lineage graph showing exactly how every model connects.

### Database Schema (public schema - loaded by migrate.py)

**raw_transactions** - full 541,909 row transaction table with indexes on invoice_date, customer_id, country, and stock_code.

**kpi_results** - 22 aggregate KPI totals from the Python pipeline. These are snapshot values per pipeline run, not a time series. The weekly time series is computed by dbt.

**anomalies** - 46 detected anomalies with kpi_name, anomaly_date, severity, confidence, actual/expected values, deviation_pct, and detection_methods (array of methods that flagged each point).

**root_causes** - 77 dimensional driver rows, one per anomaly-dimension-segment combination. Each row has anomaly_id (foreign key), dimension, segment_value, contribution_pct, and segment_rank. Multiple rows per anomaly, ranked by contribution.

**llm_calls** - 76 logged LLM calls with prompt_version, latency_ms, input/output tokens, estimated cost, and quality flags per call.

**narratives** - 38 generated narratives (19 standard, 19 RAG), with narrative_type, prompt_version, anomaly_id, and full narrative text.

### dbt Models

The dbt project lives in `ecommerce_analytics/` and is structured in three layers.

**Staging layer** (`models/staging/`)

`stg_transactions` - a view over raw_transactions that casts types, renames columns for consistency, filters out returns (quantity <= 0) and zero-price records (unit_price <= 0), adds a computed `line_total` column (quantity x unit_price), and adds `week_start` (date truncated to the Monday of each week). Reduces 541,909 rows to 530,104 after filtering.

**Intermediate layer** (`models/intermediate/`)

`int_weekly_transactions` - a view that groups the staging data by week_start, country, and stock_code. Computes order_count, unique_customers, units_sold, revenue, revenue_per_order, and revenue_per_customer at the country-product-week grain. This is the business logic layer - all aggregation happens here before the mart summarises it further.

**Mart layer** (`models/mart/`)

`mart_weekly_kpis` - a table (materialised, not a view) that summarises the intermediate layer to the week grain only, collapsing across country and product. Produces 53 rows - one per week - with total_revenue, order_count, units_sold, active_customers, revenue_per_order, and revenue_per_customer. This is the primary table Power BI reads.

`mart_anomaly_summary` - a table that joins the anomalies source table to root_causes, filtering to segment_rank = 1 to get the top driver per anomaly. Produces one row per anomaly enriched with the top contributing dimension, segment, and contribution_pct. This powers the anomaly drill-through pages in Power BI.

### Data Tests

5 automated tests defined in `models/staging/sources.yml`, run with `dbt test`:

- `raw_transactions.id` - not_null
- `raw_transactions.id` - unique
- `raw_transactions.invoice_no` - not_null
- `raw_transactions.quantity` - not_null
- `raw_transactions.unit_price` - not_null

All 5 pass on the current dataset.

### Power BI Report

4-page report connected to the `analytics` schema in PostgreSQL via psqlODBC (ODBC connector). Reads from `mart_weekly_kpis` and `mart_anomaly_summary` using Import mode.

**Page 1 - Executive Overview:** 3 KPI cards (total revenue, order count, active customers) and a weekly line chart of total_revenue across the full Dec 2010 to Dec 2011 period. The November 2011 pre-Christmas spike is clearly visible.

**Page 2 - Anomaly Monitor:** Bar chart of anomaly count by severity (low/medium/high/critical), bar chart of anomaly count by KPI name, and a detail table showing anomaly_date, kpi_name, severity, average deviation_pct, top_dimension, and top_segment per anomaly.

**Page 3 - Root Cause Analysis:** Bar chart of average top_contribution_pct by kpi_name showing which KPIs have the clearest dimensional attribution, and a detail table with the full driver breakdown per anomaly. Note: top_segment is dominated by United Kingdom across all anomalies, reflecting the dataset's composition (approximately 90% UK transactions). This is expected behaviour - the root cause engine is correctly identifying the dominant segment. In a more geographically balanced dataset, this page would surface more varied regional drivers.

**Page 4 - KPI Trends:** Six side-by-side weekly line charts covering total_revenue, order_count, active_customers, revenue_per_customer, revenue_per_order, and units_sold. Designed to show cross-metric correlation - the November 2011 wholesale event is visible as a simultaneous spike across all six panels.

### GitHub Actions CI/CD

Two workflows in `.github/workflows/`:

**dbt_ci.yml** - triggers on every push to any branch. Spins up a PostgreSQL 15 service container, installs dbt-postgres 1.9.0, creates a profiles.yml targeting the service container, runs `sql/init.sql` to initialise the schema, then runs `dbt deps`, `dbt compile`, and `dbt test --select source:*`. This validates SQL syntax across all models and runs all 5 source schema tests on every push.

**python_ci.yml** - triggers on pull requests to main. Installs pytest and project dependencies, then runs `tests/` with verbose output.

**tests/test_config.py** - 8 tests covering the kpis.yaml config file: valid YAML, correct structure, all KPIs have formula/owner/thresholds fields, anomaly_sensitivity values are valid floats between 0 and 1, metadata block exists, and all 6 core KPIs present in the mart tables are defined in config.

### Lineage Graph

Running `dbt docs generate && dbt docs serve` produces a full documentation site including a visual lineage graph:

```
public.raw_transactions --> stg_transactions --> int_weekly_transactions --> mart_weekly_kpis
public.anomalies ----------------------------------------------------------------> mart_anomaly_summary
public.root_causes --------------------------------------------------------------> mart_anomaly_summary
```

Green nodes are source tables loaded by Python. Blue nodes are dbt-managed models. The graph makes the full data flow visible without reading any code.

### Running dbt

```bash
cd ecommerce_analytics

dbt run
dbt test
dbt docs generate && dbt docs serve
# Open docs at http://localhost:8080
```

---

## Project Structure

```
ecommerce-data-storytelling/
├── .github/
│   └── workflows/
│       ├── dbt_ci.yml               # dbt compile + schema tests on every push
│       └── python_ci.yml            # pytest on every PR
├── config/
│   ├── kpis.yaml                    # 16 metric definitions (formula, owner, thresholds)
│   ├── data_contracts.yaml          # Data validation rules and schema
│   └── prompts.yaml                 # Versioned LLM prompt templates (v1, v2)
├── src/
│   ├── config/
│   │   └── tenant_config.py         # Path resolution - single-tenant now, multi-tenant ready
│   ├── data/
│   │   ├── ingestion.py
│   │   ├── validation.py
│   │   └── database.py              # PostgreSQL connection, bulk insert, upsert helpers
│   ├── kpis/
│   │   ├── formulas.py
│   │   ├── registry.py
│   │   └── engine.py
│   ├── insights/
│   │   ├── models.py
│   │   ├── methods.py
│   │   ├── detector.py
│   │   ├── results.py
│   │   └── analyser.py
│   ├── narratives/
│   │   ├── monitor.py               # LLM call logging (latency, cost, quality flags)
│   │   ├── narrator.py              # Standard narrative generation via Groq
│   │   ├── retriever.py             # ChromaDB vector store + similarity search
│   │   └── rag_narrator.py          # LangChain RAG pipeline with retrieved context
│   └── platforms/
│       ├── precompute.py            # Runs pipeline, saves parquet cache for dashboard
│       ├── dashboard.py             # Streamlit app (5 pages)
│       └── ai_lab.py                # AI Lab page - monitoring, comparison, prompt history
├── ecommerce_analytics/             # dbt project
│   ├── models/
│   │   ├── staging/
│   │   │   ├── stg_transactions.sql
│   │   │   └── sources.yml          # Source definitions and 5 data tests
│   │   ├── intermediate/
│   │   │   └── int_weekly_transactions.sql
│   │   └── mart/
│   │       ├── mart_weekly_kpis.sql
│   │       └── mart_anomaly_summary.sql
│   └── dbt_project.yml
├── sql/
│   └── init.sql                     # PostgreSQL schema - 6 tables, indexes, 3 views
├── scripts/
│   └── migrate.py                   # Idempotent migration from CSV/JSON/JSONL to Postgres
├── tests/
│   └── test_config.py               # 8 pytest tests covering kpis.yaml structure
├── data/
│   ├── raw/
│   │   └── UK retail data.csv       # 541,909 rows
│   ├── processed/
│   │   └── kpi_results.csv
│   ├── insights/
│   │   ├── anomalies.csv
│   │   ├── root_causes.csv
│   │   ├── narratives.json
│   │   └── rag_narratives.json
│   ├── monitoring/
│   │   └── llm_calls.jsonl
│   └── cache/                       # Precomputed parquet files (gitignored)
├── docker-compose.yaml              # PostgreSQL 15 with health check and named volume
└── README.md
```

---

## Running the Code

**Important:** All Python modules should be run from the project root directory using the `-m` flag. This ensures proper import resolution and path handling.

### Setup

```bash
cd path/to/ecommerce-data-storytelling
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Mac/Linux
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file in the project root:

```
GROQ_API_KEY=your_key_here
```

Get a free key at [console.groq.com](https://console.groq.com).

### Starting the Database

```bash
docker-compose up -d
# Wait ~10 seconds for health check, then:
python scripts/migrate.py
```

### Running the Python Pipeline

```bash
python -m src.data.ingestion
python -m src.data.validation
python -m src.kpis.engine
python -m src.insights.detector
python -m src.insights.analyser
python -m src.platforms.precompute
python -m src.narratives.narrator
python -m src.narratives.rag_narrator
streamlit run src/platforms/dashboard.py
```

### Running dbt

```bash
cd ecommerce_analytics
dbt run
dbt test
dbt docs generate && dbt docs serve
# Open http://localhost:8080
```

---

## Dashboard Pages

**Overview** - 16 KPI cards with trend arrows and anomaly indicators. Red dot = anomaly detected for that metric.

**Time Series** - Weekly KPI line chart with coloured dashed vertical lines marking anomaly dates by severity (green=low, orange=high, red=critical).

**Anomalies** - Filterable anomaly table. Click any row to see the root cause bar chart and LLM narrative for that anomaly.

**Insights** - The November 2011 event visualised as a normalised 4-KPI chart, with AI narrative summaries for each anomaly in the cluster.

**AI Lab** - LLM observability and evaluation:
- Monitoring - live stats for every API call (total calls, success rate, cost, latency, quality flags by prompt version)
- Narrative Comparison - pick any anomaly and compare standard vs RAG narrative side by side with retrieved context documents shown
- Prompt Versions - full template history from `config/prompts.yaml` with call counts, violation rates, and latency per version

---

## Dataset

Using real UK retail transaction data with:
- **541,909 transactions** over 13 months (Dec 2010 - Dec 2011)
- **4,070 unique products** sold across **38 countries**
- **4,372 unique customers** with purchase history

**Columns:** InvoiceNo, InvoiceDate, CustomerID, StockCode, Description, Quantity, UnitPrice, Country

I picked this dataset because it's real business data with actual messiness - missing CustomerIDs, negative quantities for returns, outliers - rather than a clean synthetic dataset. This makes it better for demonstrating data quality practices.

Source: UCI ML Repository (Online Retail Dataset)

---

## Metrics Tracked

16 KPIs across 5 business areas:

**Finance:** total revenue, revenue per order, revenue per customer

**Operations:** order count, items per order, units sold, product return rate, weekend revenue share, peak hour concentration

**Growth:** active customers, repeat customer rate, new customers

**Product:** product revenue concentration, avg unit price

**International:** revenue by country, international revenue share

Each metric has an owner (Finance, Operations, etc.), a cadence (daily or weekly), and anomaly detection thresholds.

---

## Development Plan

### Phase 1: Foundation 
Set up project structure, defined all 16 metrics in config files, documented data validation rules, planned architecture.

### Phase 2: Data Pipeline 
Built data loader with proper encoding (latin-1 for special characters), implemented 14 automated quality checks, achieved 71.4% data quality score with 4 documented anomalies.

### Phase 3: KPI Computation Engine 
Built a config-driven formula parser that executes metric definitions from YAML dynamically. The trickiest parts were handling cross-KPI dependencies (where one metric references another), conditional filtering (e.g. revenue from non-UK customers only), and complex aggregations like top-N product revenue that can't be expressed as simple formulas.

**Key challenge solved:** The formula parser needs to check ratio patterns (`/`) before aggregate patterns (`sum(`, `count(`) - otherwise `sum(Quantity) / order_count` gets partially consumed by the aggregate check and the division is ignored.

### Phase 4: Anomaly Detection 
Three detection methods running in parallel across all KPIs. Z-score catches sudden spikes by measuring standard deviations from the mean. IQR is more robust - it uses the middle 50% of data so extreme values don't distort what counts as normal. Mann-Kendall detects gradual trends rather than point anomalies - it flagged that revenue, orders, and active customers were all on a statistically significant upward trajectory through 2011.

The trickiest part was the baseline problem: with only 13 months of data, the Christmas 2010 spike is part of the same dataset you're detecting anomalies in. A configurable `baseline_window` parameter excludes that period so "normal" is calculated on the non-seasonal months only.

When multiple methods flag the same KPI on the same date, confidence gets boosted. A point that Z-score and IQR both flag independently is stronger evidence than either alone.

### Phase 5: Root Cause Analysis 
For each detected anomaly, the analyser filters raw transaction data to the anomaly week and slices by Country, StockCode, and HourOfDay. It calculates how much each segment contributed to the total deviation relative to the baseline, then ranks them by impact.

The key design decision was to flag ratio KPIs for manual review rather than analyse them naively. Slicing repeat_customer_rate by Country would require recalculating the numerator and denominator separately per country - just filtering the data and recalculating the ratio produces numbers that look plausible but are wrong.

The most interesting finding: four separate anomalies in November 2011 all pointed to the same two products bought by UK customers at high volumes during afternoon hours across three consecutive weeks. One event, four metrics.

### Phase 6: Dashboard, Narratives, and AI Layer 
Streamlit dashboard with 5 pages and Plotly visualisations. Precompute layer saves all pipeline outputs to parquet cache so the dashboard loads instantly without re-running the pipeline.

LLM narratives generated via Groq (free tier, Llama 3.1-8b-instant). Every call logged through a monitoring layer to JSONL - latency, token usage, estimated cost, and output quality flags per call. Prompt templates versioned in `config/prompts.yaml`. The v1 to v2 prompt change reduced quality violations from 8/19 (42%) to 0/19 (0%) - caught and confirmed through the monitoring layer.

RAG pipeline built with LangChain LCEL + ChromaDB + sentence-transformers. A cross-KPI retrieval bug caused hallucinations in the first run - fixed by adding `same_kpi_only=True` metadata filtering to ChromaDB retrieval. AI Lab dashboard page gives full visibility into monitoring stats, narrative comparison, and prompt version history.

### Phase 7: PostgreSQL + dbt + Power BI + CI/CD (Complete)

#### PostgreSQL migration
Migrated all pipeline outputs to PostgreSQL 15 running in Docker. `scripts/migrate.py` is idempotent, but getting there properly took two passes: `kpi_results`, `anomalies`, and `narratives` have real unique constraints and use genuine `ON CONFLICT` upsert logic, `root_causes` got a `UNIQUE (anomaly_id, segment_rank)` constraint during the Phase 7.5 hardening pass once the actual insert grain was worked out, and `raw_transactions`/`llm_calls` always truncate before reload since checking the real data confirmed neither has a safe natural key to upsert against. Final verified counts on a clean run: raw_transactions 541,909, kpi_results 22, anomalies 46, root_causes 77, llm_calls 76, narratives 38.

The schema in `sql/init.sql` includes indexes on all query columns and three pre-built views: `vw_kpi_with_anomaly_flag`, `vw_llm_monitoring_summary`, and `vw_anomaly_clusters`.

#### dbt transformation layer
Built a four-model dbt pipeline that replaces the Python pipeline's flat CSV outputs with SQL-computed mart tables. The three-layer architecture (staging, intermediate, mart) keeps cleaning, business logic, and reporting concerns cleanly separated.

The key design decision: the existing `kpi_results` table only stores 22 aggregate totals - one per pipeline run. The proper weekly KPI time series is computed by dbt directly from `raw_transactions` in SQL, producing 53 rows (one per week) in `mart_weekly_kpis`. This is the correct approach - the Python engine was always designed to hand off time-series computation to the database layer.

`mart_weekly_kpis` materialises as a table (not a view) so Power BI reads from pre-computed results rather than running aggregations on 530k rows at query time. Staging and intermediate models are views - they stay fresh without storage cost.

5 data tests pass on every `dbt test` run, and `dbt docs generate` produces a full documentation site with a visual lineage graph.

#### Power BI reporting layer
Connected Power BI Desktop to the analytics schema via psqlODBC. Built a 4-page report reading from `mart_weekly_kpis` and `mart_anomaly_summary` in Import mode.

The report surfaces the weekly revenue trend across the full dataset period, anomaly distribution by severity and KPI, root cause contribution by KPI, and side-by-side KPI trend lines for all 6 mart metrics. The November 2011 pre-Christmas wholesale event is visible as a correlated spike across all six KPI trend panels simultaneously.

Known limitation: the root cause page is dominated by United Kingdom as the top segment across all anomalies. This reflects the dataset composition (approximately 90% UK transactions) rather than a reporting error. A more geographically balanced dataset would surface more varied regional drivers.

#### GitHub Actions CI/CD
Two workflows wired to the repository. `dbt_ci.yml` runs on every push - it spins up a PostgreSQL 15 service container, pins dbt-core and dbt-postgres to 1.9.0, creates a profiles.yml targeting the service container, initialises the schema from `sql/init.sql`, and runs `dbt compile` followed by `dbt test --select source:*`. `python_ci.yml` runs on every PR to main and executes the pytest suite in `tests/`.

The dbt version pin matters: dbt-core 2.0.0-alpha.2 dropped postgres adapter support in favour of dbt Fusion. Pinning to 1.9.0 keeps the workflow stable.

### Phase 7.5: Operational Hardening - Running It For Real

Everything through Phase 7 had been verified by reading the code, running unit-level checks, and running each layer in isolation. It had never been run start to finish against live infrastructure - a real Postgres container, a real LLM API, a real Windows terminal - in one continuous pass. Phase 7.5 was that pass, and it found a category of bug that code review structurally cannot see.

#### Round 1: multi-domain code review

Four focused reviews ran in parallel against the codebase - Python pipeline, the RAG/LLM narrative layer, the dbt/SQL layer, and a security pass. Combined, they surfaced two CRITICAL and roughly a dozen HIGH/MEDIUM findings, all fixed:

- **`migrate.py` transaction handling** - when a bulk insert failed, the row-by-row fallback ran on the same connection without rolling back first, so Postgres rejected every row with "transaction aborted" instead of surfacing the actual bad row. A second bug in the same fallback let a later row's rollback silently erase earlier rows that had already succeeded, while the success counter kept counting them.
- **Division by zero in `int_weekly_transactions.sql`** - `SUM(line_total) / COUNT(distinct customer_id)` had no `NULLIF` guard, unlike the equivalent line in `mart_weekly_kpis.sql`. With 24.9% of transactions missing a `customer_id` (guest checkouts), any weekly/country/product group made up entirely of guests would crash the dbt build.
- **SQL identifiers built via f-string interpolation** in `database.py`'s bulk insert/upsert/truncate helpers - not exploitable with the current hardcoded call sites, but a shared utility one careless future caller away from injection. Added an allow-list identifier validator.
- **Hardcoded fallback database password** (`analytics_dev`) - silently used if `POSTGRES_PASSWORD` was ever unset, instead of failing loudly. Changed to raise if the environment variable is missing.
- **`tenant_id` used unvalidated in filesystem paths and vector store collection names** - a `TenantConfig` field with a documented multi-tenant future and no validation is a path-traversal bug waiting for its first untrusted caller. Added an allow-list regex.
- **RAG retrieval quality** - the similarity query was a near-constant string per KPI ("KPI: Total Revenue. Anomaly detected."), so "3 most similar historical anomalies" was mostly noise. Anchored the query to the anomaly's actual severity, direction, and magnitude, and added a distance cutoff so weak matches get dropped instead of presented as meaningful history.
- **RAG cost/token tracking was silently hardcoded to zero** - the LangChain LCEL chain was piped through `StrOutputParser`, which discards the response metadata that carries real token counts. Every `v2-rag` row in the monitoring log showed `$0.00`, masking that RAG prompts cost more than standard ones. Fixed by keeping the raw `AIMessage` and reading its usage metadata directly.

#### Round 2: actually running it

Static review, however thorough, only checks whether code looks correct. Running it against real infrastructure found bugs that no amount of reading would have surfaced:

- **Windows console `UnicodeEncodeError`** - `print()` and `logging` calls throughout the pipeline use checkmarks, box-drawing characters, £, and arrows. Windows' default console codepage (cp1252) can't encode them, so `validation.py` and `kpis/engine.py` crashed the instant they tried to print a result. Fixed once, centrally, by reconfiguring stdout/stderr to UTF-8 in `src/__init__.py` rather than hunting down every individual character across a dozen files.
- **Groq fully deprecated the narrative model.** `llama-3.1-8b-instant` - the model both `narrator.py` and `rag_narrator.py` are built around - no longer exists on Groq's API. This was invisible in a normal pipeline run because every anomaly already had a cached narrative from before the deprecation; only a genuinely new anomaly would have hit the dead model and failed silently. Checked the account's live model list, tested three replacement candidates against the actual prompt: two (`openai/gpt-oss-20b`, `qwen/qwen3.6-27b`) are reasoning models that burned the entire token budget on hidden chain-of-thought and returned empty output at the project's existing `max_tokens=200`. `allam-2-7b` behaved like a normal instruct model and produced clean, on-topic narratives at the existing settings - selected and verified with real API calls.
- **A stale WSL2 port relay was stealing the database connection.** After starting Docker, `scripts/migrate.py` failed with a password error even with the correct password. `netstat` showed two separate processes listening on port 5432 - Docker's own proxy, and a leftover `wslrelay.exe` bound specifically to the IPv6 loopback address, left over from a previous session. Since Windows resolves `localhost` to `::1` first, every connection was being silently routed through the dead relay. Killed the stale process; the real connection worked immediately.
- **The database's real password was unknown.** Even after clearing the port conflict, authentication still failed. The Postgres container's data volume was initialised five months earlier with whatever `POSTGRES_PASSWORD` was in effect *then* - environment variables only set the password on first initialisation, not on every container start - and that value matched neither `docker-compose.yaml`'s current default nor a third, different password sitting in a personal, untracked `~/.dbt/profiles.yml`. Diagnosed by reading `pg_hba.conf` inside the container: loopback connections are `trust`-authenticated (no password check at all), which is why an earlier sanity check via `docker exec` had given a false "it works" - it never actually validated anything. Reset the real password through that trusted local connection, then reconciled all three credential sources to agree.
- **A silent data-duplication bug, caught only by not trusting the tool's own numbers.** `psycopg2`'s `execute_values` pages large inserts internally (100 rows per page by default) and only reports the *last* page's row count afterward - so a 541,909-row load logged "5,409 rows inserted" while the real database had actually received the full amount. That misreporting was hiding a worse problem: `raw_transactions` and `root_causes` have no unique constraint, so `ON CONFLICT DO NOTHING` never had anything to conflict against, and a second migration run silently doubled both tables (541,909 -> 1,083,818; 77 -> 154). This was only caught by running `SELECT COUNT(*)` directly against the database instead of trusting the migration script's printed summary. Fixed the rowcount bug by forcing a single `execute_values` page, and fixed the duplication properly rather than working around it again: checked whether `raw_transactions` actually has a safe natural key first (it doesn't - 9,694 groups of `invoice_no + stock_code` legitimately repeat as separate line items in the real dataset), so that table and the append-only `llm_calls` log now always truncate before reload, while `root_causes` got a real `UNIQUE (anomaly_id, segment_rank)` constraint. Verified by running the migration twice in a row with zero row growth on the second run.

None of these five would have turned up in a code review, however careful. The rowcount bug is the clearest example: the fix wasn't spotting bad code, it was distrusting a log line that said "5,409 rows inserted" and running `SELECT COUNT(*)` against the actual database instead.

### Phase 8 (Planned)
AWS deployment - EC2, RDS, S3. FastAPI layer. Live public URL.

---

## Technical Approach

**Config-Driven Design** - metrics defined in YAML, not Python. Business logic is separate from implementation. Inspired by how dbt handles metric definitions.

**Statistical Methods** - three methods were chosen deliberately, each catching a different type of problem. Z-score is the most interpretable. IQR is robust to skewed distributions like retail revenue. Mann-Kendall is non-parametric and catches gradual drift rather than point anomalies. Running all three in parallel means sudden spikes, distributional outliers, and trends are all covered. Confidence boosting when multiple methods agree keeps false positive rates manageable.

**Layered Architecture** - each layer has a single responsibility: ingest, validate, compute, detect, analyse, narrate, store, transform, report. Adding or replacing any layer doesn't require touching the others.

**Production Structure** - modular code organised by responsibility, proper error handling and logging, type hints on public functions.

**Data Quality First** - explicit validation before any analysis. The system fails loudly on threshold breaches rather than silently accepting bad data.

---

## Tech Stack

- Python 3.10+, Pandas, NumPy
- SciPy and Statsmodels
- PyYAML for config parsing
- Streamlit, Plotly
- Groq (allam-2-7b, previously Llama 3.1-8b-instant until Groq deprecated it), LangChain, ChromaDB, sentence-transformers
- PostgreSQL 15, Docker, psycopg2
- dbt (dbt-postgres 1.9.0)
- Power BI Desktop (connected via psqlODBC)
- Parquet (cache), JSONL (monitoring log)
- pytest, black, ruff
- GitHub Actions (CI/CD)
- Git with conventional commits

---

## Known Issues / TODOs

- No comprehensive test suite yet - current pytest coverage is limited to config validation
- `new_customers` will equal `active_customers` on this dataset - we only have one year of data, so every customer's first order falls within the dataset period. In production you'd compare against a historical customer table.
- `revenue_by_country` currently returns total revenue as a scalar. The actual per-country breakdown will be handled as a visualisation later.
- Config YAML validation is basic - could add schema validation
- Root cause contribution percentages can exceed 100% for the primary driver. This is not a calculation error - it happens when the dominant segment overperforms while other segments are simultaneously below their baseline. The number is mathematically correct but looks odd without that explanation.
- Power BI root cause page shows United Kingdom as the dominant segment for all anomalies, reflecting dataset composition rather than a reporting error.
- `allam-2-7b` (the Groq model narratives now run on, after `llama-3.1-8b-instant` was deprecated - see Phase 7.5) follows the prompt's formatting instructions less reliably than the old model did. Quality flag rates roughly doubled after the switch. Not broken, just a prompt that needs re-tightening for the new model.

---

## What I'm Learning

This project is forcing me to think about things I didn't expect:

- How much time goes into decisions that seem trivial - "should this be a separate module?", "what should I name this function?" Software design is probably 20% coding and 80% deciding how to organise things.
- Real data is never clean. The 71.4% quality score isn't a failure, it's the validation system working correctly.
- The difference between "works in a notebook" and "works in production" is enormous. Reproducibility, error handling, and modular structure matter a lot more than I initially appreciated.
- When building a formula parser, ordering of checks matters. Ratio detection must come before aggregate detection or compound formulas break silently.
- Baseline selection matters more than algorithm choice. The same Z-score threshold produces completely different results depending on whether you include a known seasonal spike in your baseline.
- Multiple detection methods catching the same anomaly is much more meaningful than any single method - the confidence boosting logic ended up being one of the more useful design decisions.
- Root cause analysis taught me that the same event can show up as multiple separate anomalies. Automated analysis caught something that would have taken an analyst a while to piece together manually.
- Prompts are code. They need versioning, testing, and measurement. Changing a prompt without tracking what changed and whether it helped is the same mistake as changing production code without version control.
- Observability first. You cannot evaluate an AI system you cannot observe. The monitoring layer needed to exist before the RAG layer, not after.
- SQL is the right tool for aggregations at scale. Moving KPI time series computation from Python/pandas into dbt SQL reduced the problem to a clean GROUP BY and made the logic auditable, testable, and directly queryable - things you can't easily do with a pandas DataFrame saved to parquet.
- Separation of concerns compounds. Having staging clean the data, intermediate apply business logic, and mart produce reporting-ready tables means each layer can be changed, tested, and documented independently. The lineage graph makes every dependency explicit.
- CI/CD version pinning matters in practice. The dbt 2.0.0-alpha.2 pre-release silently broke postgres support - without an explicit version pin in the workflow, the pipeline would have failed unpredictably whenever a new pre-release shipped.
- Power BI dominant-segment bias is a known limitation in dimensional root cause analysis. When one segment holds 90%+ of volume, contribution-weighted metrics will always surface it as the top driver regardless of whether it's actually anomalous. The fix is normalised contribution metrics that account for expected share, not raw contribution.

---

## Acknowledgments

- **Dataset:** UCI Machine Learning Repository (Online Retail Dataset)
- **Inspiration:** Reading about how Looker, Mode, and dbt structure metric definitions
- **Statistical methods:** SciPy docs, stats coursework, StackOverflow
- **Architecture patterns:** Various blog posts on analytics engineering

---

## How I Built This With AI Assistance

This project was built using Claude as a pair programming tool throughout. I'm documenting this deliberately rather than omitting it - transparency about AI-assisted development is more useful than pretending it didn't happen, and the way I used it is worth explaining.

### The workflow

I directed the architecture and made every significant design decision. Claude generated implementation. I reviewed, tested, caught bugs, and directed fixes. The split in practice: I specified what to build and why, Claude wrote the first version, I ran it and evaluated whether it worked correctly, and we iterated from there.

This is not meaningfully different from how senior engineers use AI tools now. The skill is in knowing what to build, recognising when the output is wrong, and understanding the system well enough to debug it. Generating code is the easy part.

### What the AI got wrong - and how I caught it

These are real bugs that appeared during the build and required actual diagnosis to fix:

**KPI calculation errors in the README** - The README documented `repeat_customer_rate` as ~83% and `product_revenue_concentration` as ~47%. Both were wrong, carried over from an earlier phase when the engine had formula bugs. I caught them by running a manual verification audit against the raw data and comparing every value in the README against the engine output. The engine was correct; the README had never been updated. Corrected to 70% and 14% respectively.

**Date axis showing year 2035** - The time series chart was displaying years starting from 2035 instead of 2011. The root cause was that the KPI engine returns a `date` column in the DataFrame rather than setting it as the index, so the dashboard was receiving a plain integer RangeIndex (0, 1, 2...) which Plotly interpreted as epoch offsets. Fixed by explicitly calling `set_index('date')` in `precompute.py` before saving to parquet. The fix required understanding the full data flow from engine output to parquet to dashboard render - not just changing one line.

**RAG hallucination from cross-KPI retrieval** - The first RAG run retrieved `product_revenue_concentration` anomalies when generating a narrative for a `total_revenue` anomaly, because the vector similarity search matched document structure rather than business meaning. The LLM then fabricated a reference to a revenue spike in January 2011 that didn't exist. I caught it by comparing the retrieved context IDs against the anomaly being narrated and recognising the mismatch. Fixed by adding a `same_kpi_only=True` metadata filter to ChromaDB retrieval. The monitoring layer confirmed zero hallucinations after the fix.

**Prompt violations caught by monitoring** - 8 out of 19 v1 narratives contained percentages, violating the explicit prompt instruction not to use them. I wouldn't have caught this by reading outputs manually - 8/19 is easy to miss when skimming. The monitoring layer flagged it automatically. The fix was tightening the v2 prompt wording, and the monitoring log confirmed the violation rate dropped from 42% to 0%.

**Duplicate rows from repeated migration runs** - Running `migrate.py` multiple times without resetting the database produced 1,625,727 rows in raw_transactions (3 x 541,909) and 154 rows in root_causes (2 x 77). Caught by running a COUNT(*) verification query after each migration. At the time, fixed by running `docker-compose down -v` to wipe the volume and re-migrating once cleanly - which worked, but only masked the actual cause. It recurred during the Phase 7.5 hardening pass (see below) because neither table had ever had a unique constraint capable of making `ON CONFLICT DO NOTHING` actually do anything; `docker-compose down -v` just reset the symptom, not the bug. That pass added the real fix: a genuine `UNIQUE (anomaly_id, segment_rank)` constraint on root_causes, and always-truncate-before-load semantics for raw_transactions once checking the actual data confirmed it has no safe natural key. A workaround that makes the symptom go away isn't the same as understanding why it happened - it comes back.

**dbt column name mismatch** - The initial `mart_anomaly_summary` model referenced `a.date` and `r.driver_1_dimension`, neither of which existed in the actual schema. The anomalies table uses `anomaly_date`, and root_causes stores drivers as individual rows with `dimension`, `segment_value`, and `segment_rank` columns rather than denormalised driver_1/driver_2/driver_3 columns. Caught by running `dbt run` and reading the Database Error output, then inspecting the actual schema with `\d anomalies` and `\d root_causes` in psql. Fixed by rewriting the mart model to filter `segment_rank = 1` and join on the correct column names.

**dbt CI pre-release version conflict** - The initial GitHub Actions workflow pulled dbt-core 2.0.0-alpha.2 from PyPI, which dropped postgres adapter support in favour of dbt Fusion. The workflow failed immediately with an InvalidConfig error. Fixed by pinning both dbt-core and dbt-postgres explicitly to 1.9.0 in the install step. Pre-release packages on PyPI are installed by default when no version pin is specified, which makes explicit pinning essential for stable CI.

**Five more bugs that only appeared when the whole system was actually run end-to-end** - A Phase 7.5 hardening pass (full write-up under "Phase 7.5: Operational Hardening" above) went beyond code review and ran ingestion through dbt in one continuous pass against live infrastructure: a Windows console encoding crash, a fully deprecated LLM model masked by narrative caching, a stale WSL2 network relay silently stealing the database connection, a lost database password across three disagreeing credential sources, and a `psycopg2` rowcount bug that hid a real data-duplication issue.

### What this taught me about working with AI tools

**Prompts are code.** They need versioning, testing, and measurement. The prompt versioning system in `config/prompts.yaml` exists because I learned mid-project that changing a prompt without tracking what changed and whether it helped is the same mistake as changing production code without version control.

**Observability first.** The monitoring layer was built before the RAG layer specifically because you cannot evaluate an AI system you cannot observe. This is the same principle as adding logging and metrics before scaling a service - you need to be able to see what's happening before you can improve it.

**AI accelerates implementation, not understanding.** The design decisions in this project - baseline windowing, ratio KPI flagging, JSONL for monitoring logs, TenantConfig for path resolution, dbt three-layer architecture - all came from thinking through the problem before writing code. AI generated the implementation quickly once the design was clear. Where I skipped the thinking step and let AI drive the design, the results needed more rework.

**Verification is the job.** The KPI audit, the date axis debugging, the RAG hallucination diagnosis, the migration duplicate detection, the dbt schema mismatch, the CI version conflict - none of these were caught by AI. They were caught by running the system, looking at the output, and asking whether it was correct. That's the work that remains irreducibly human regardless of how good the code generation gets.

### What I can explain without AI assistance

Every layer of this system. The statistical methods and why three were chosen. The formula parser and why check ordering matters. The baseline windowing decision and what happens if you get it wrong. The dimensional slicing approach and why ratio KPIs can't be segmented naively. The RAG architecture and the specific failure mode that caused the hallucination. The JSONL monitoring format and why it was chosen over a database. The dbt three-layer architecture and why mart models are materialised as tables while staging and intermediate are views. The lineage graph and what each dependency represents. The CI version pinning issue and why pre-release packages break stable workflows.

If an interviewer wants to walk through any part of this codebase, I can explain the design decisions, the tradeoffs, and what I would do differently.

---

**Status:** Phase 7.5 Complete  
**Next:** Phase 8 - AWS deployment (EC2, RDS, S3), FastAPI layer, live public URL

*Second year CS student building this to understand how production analytics systems actually work. Building in phases rather than a fixed schedule - shipping each layer properly before moving to the next.*

Last updated: September 2026