"""
scripts/migrate.py

One-time migration script that loads all existing pipeline outputs into PostgreSQL.

Usage:
    python -m scripts.migrate
    python -m scripts.migrate --reset   # truncate all tables and reload
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.database import get_connection, insert_dataframe, upsert_dataframe, truncate_table

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]


def _log_step(step: str, n: int) -> None:
    logger.info(f"  ✓  {step:<35} {n:>7,} rows")

def migrate_raw_transactions(conn, reset: bool = False) -> int:
    csv_path = ROOT / "data" / "raw" / "UK retail data.csv"
    if not csv_path.exists():
        logger.warning(f"Raw CSV not found, skipping")
        return 0

    logger.info("Loading raw transactions...")
    df = pd.read_csv(csv_path, encoding="latin-1", parse_dates=["InvoiceDate"])
    df = df.rename(columns={
        "InvoiceNo":   "invoice_no",
        "StockCode":   "stock_code",
        "Description": "description",
        "Quantity":    "quantity",
        "InvoiceDate": "invoice_date",
        "UnitPrice":   "unit_price",
        "CustomerID":  "customer_id",
        "Country":     "country",
    })
    df["customer_id"] = df["customer_id"].apply(
        lambda x: str(int(x)) if pd.notna(x) else None
    )
    df["loaded_at"] = datetime.now()
    cols = ["invoice_no", "stock_code", "description", "quantity",
            "invoice_date", "unit_price", "customer_id", "country", "loaded_at"]

    # raw_transactions has no safe natural key - a real invoice can
    # legitimately repeat the same stock_code as separate line items
    # (9,694 such groups exist in this dataset), so ON CONFLICT DO NOTHING
    # can never actually deduplicate it. It's meant to fully mirror the CSV,
    # so always truncate first rather than risk doubling it on every re-run.
    truncate_table("raw_transactions", conn)

    batch_size = 10_000
    total = 0
    batches = [df[cols].iloc[i:i+batch_size] for i in range(0, len(df), batch_size)]
    for i, batch in enumerate(batches):
        n = insert_dataframe(batch, "raw_transactions", conn, conflict_action="DO NOTHING")
        total += n
        logger.info(f"    batch {i+1}/{len(batches)} — {total:,} rows so far")

    _log_step("raw_transactions", total)
    return total

def migrate_kpi_results(conn, reset: bool = False) -> int:
    csv_path = ROOT / "data" / "processed" / "kpi_results.csv"
    if not csv_path.exists():
        logger.warning("kpi_results.csv not found, skipping")
        return 0

    logger.info("Loading KPI results...")
    df = pd.read_csv(csv_path)
    logger.info(f"  columns: {list(df.columns)}")

    # Find the date column
    meta_cols = ["timestamp", "calculation_date", "date", "week_date", "period", "week"]
    date_col = next((c for c in meta_cols if c in df.columns), None)
    if date_col is None:
        raise ValueError(f"No date column found. Columns: {list(df.columns)}")

    # Melt wide → long: one row per (kpi_name, week_date)
    kpi_cols = [c for c in df.columns if c not in meta_cols]
    df = df[[date_col] + kpi_cols].copy()
    df = df.melt(id_vars=[date_col], value_vars=kpi_cols,
                 var_name="kpi_name", value_name="value")
    df = df.rename(columns={date_col: "week_date"})
    df["week_date"] = pd.to_datetime(df["week_date"])
    df = df.dropna(subset=["value"])

    # Deduplicate — keep one row per (kpi_name, week_date)
    df = df.drop_duplicates(subset=["kpi_name", "week_date"], keep="last")

    df["category"] = None
    df["cadence"] = None
    df["computed_at"] = datetime.now()

    cols = ["kpi_name", "week_date", "value", "category", "cadence", "computed_at"]

    if reset:
        truncate_table("kpi_results", conn)

    n = insert_dataframe(df[cols], "kpi_results", conn, conflict_action="DO NOTHING")
    _log_step("kpi_results", n)
    return n

def migrate_anomalies(conn, reset: bool = False) -> int:
    csv_path = ROOT / "data" / "insights" / "anomalies.csv"
    if not csv_path.exists():
        logger.warning("anomalies.csv not found, skipping")
        return 0

    logger.info("Loading anomalies...")
    df = pd.read_csv(csv_path)
    logger.info(f"  columns: {list(df.columns)}")

    # Normalise date column
    date_col_candidates = ["anomaly_date", "date", "week_date", "detection_date"]
    date_col = next((c for c in date_col_candidates if c in df.columns), None)
    if date_col is None:
        raise ValueError(f"No date column found in anomalies.csv")
    if date_col != "anomaly_date":
        df = df.rename(columns={date_col: "anomaly_date"})
    df["anomaly_date"] = pd.to_datetime(df["anomaly_date"])

    
    if "confidence" in df.columns:
        df = df.sort_values("confidence", ascending=False)
    df = df.drop_duplicates(subset=["kpi_name", "anomaly_date"], keep="first")
    logger.info(f"  {len(df)} unique anomalies after dedup")

    df["detected_at"] = datetime.now()

    # Handle detection_methods column
    if "method" in df.columns:
        df["detection_methods"] = df["method"].apply(lambda x: [x] if pd.notna(x) else [])
    elif "detection_methods" in df.columns:
        df["detection_methods"] = df["detection_methods"].apply(
            lambda x: x.split(",") if isinstance(x, str) else []
        )
    else:
        df["detection_methods"] = [[] for _ in range(len(df))]

    # Map column names to schema
    col_map = {
        "deviation_pct": "deviation_pct",
        "actual_value":  "actual_value",
        "expected_value":"expected_value",
    }
    for src, dst in col_map.items():
        if src not in df.columns:
            df[dst] = None

    if "direction" not in df.columns:
        df["direction"] = df["deviation_pct"].apply(
            lambda x: "above" if pd.notna(x) and x > 0 else "below" if pd.notna(x) else None
        )

    cols = ["kpi_name", "anomaly_date", "severity", "confidence",
            "actual_value", "expected_value", "deviation_pct",
            "direction", "detection_methods", "detected_at"]

    if reset:
        truncate_table("anomalies", conn)

    n = insert_dataframe(df[cols], "anomalies", conn, conflict_action="DO NOTHING")
    _log_step("anomalies", n)
    return n


# ── root_causes ───────────────────────────────────────────────────────────────

def migrate_root_causes(conn, reset: bool = False) -> int:
    csv_path = ROOT / "data" / "insights" / "root_causes.csv"
    if not csv_path.exists():
        logger.warning("root_causes.csv not found, skipping")
        return 0

    logger.info("Loading root causes...")
    df = pd.read_csv(csv_path)
    logger.info(f"  columns: {list(df.columns)}")
    logger.info(f"  shape: {df.shape}")

    # Normalise date column
    date_col_candidates = ["anomaly_date", "date", "week_date"]
    date_col = next((c for c in date_col_candidates if c in df.columns), None)
    if date_col is None:
        raise ValueError(f"No date column found in root_causes.csv")
    if date_col != "anomaly_date":
        df = df.rename(columns={date_col: "anomaly_date"})
    df["anomaly_date"] = pd.to_datetime(df["anomaly_date"])
    df["analysed_at"] = datetime.now()

    # Fetch anomaly IDs from DB
    anomaly_id_map = {}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, kpi_name, anomaly_date::text FROM anomalies")
            rows = cur.fetchall()
        for row_id, kpi, adate in rows:
            anomaly_id_map[(kpi, str(adate)[:10])] = int(row_id)
        logger.info(f"  fetched {len(anomaly_id_map)} anomaly IDs from DB")
    except Exception as e:
        logger.warning(f"  Could not fetch anomaly IDs: {e}")

    # Build rows one driver at a time with explicit type safety
    insert_rows = []
    for _, row in df.iterrows():
        kpi_name  = str(row["kpi_name"])
        anom_date = row["anomaly_date"]
        status    = str(row.get("status", "explained"))
        analysed  = row["analysed_at"]

        # Look up anomaly_id safely
        date_key = str(anom_date)[:10]
        anomaly_id = anomaly_id_map.get((kpi_name, date_key), None)

        added = False
        for i in range(1, 4):
            dim = row.get(f"driver_{i}_dimension")
            seg = row.get(f"driver_{i}_segment")
            pct = row.get(f"driver_{i}_contribution_pct")

            dim_ok = dim is not None and not (isinstance(dim, float) and pd.isna(dim))
            seg_ok = seg is not None and not (isinstance(seg, float) and pd.isna(seg))

            if dim_ok and seg_ok:
                # Safe contribution_pct
                safe_pct = None
                if pct is not None and not (isinstance(pct, float) and pd.isna(pct)):
                    try:
                        fval = float(pct)
                        if not pd.isna(fval) and abs(fval) <= 999999.9999:
                            safe_pct = round(fval, 4)
                        elif not pd.isna(fval):
                            # clamp to safe range
                            safe_pct = round(min(max(fval, -999999.9999), 999999.9999), 4)
                    except (ValueError, TypeError):
                        safe_pct = None

                insert_rows.append((
                    anomaly_id,           # int or None  → INTEGER
                    kpi_name,             # str          → VARCHAR
                    anom_date,            # datetime     → DATE
                    status,               # str          → VARCHAR
                    str(dim),             # str          → TEXT
                    str(seg),             # str          → TEXT
                    safe_pct,             # float or None→ NUMERIC
                    i,                    # Python int   → INTEGER
                    analysed,             # datetime     → TIMESTAMP
                ))
                added = True

        if not added:
            # segment_rank=0 is a sentinel for "no driver found" (rather than
            # NULL) so UNIQUE(anomaly_id, segment_rank) can actually prevent
            # duplicate no-driver rows on re-run - Postgres treats NULL as
            # distinct from NULL, so a NULL rank would never conflict.
            insert_rows.append((
                anomaly_id, kpi_name, anom_date, status,
                None, None, None, 0, analysed,
            ))

    logger.info(f"  prepared {len(insert_rows)} rows for insert")

    # Log first row for diagnostics
    if insert_rows:
        logger.info(f"  sample row: {insert_rows[0]}")
        logger.info(f"  sample types: {[type(v).__name__ for v in insert_rows[0]]}")

    if not insert_rows:
        logger.warning("  no rows to insert")
        return 0

    if reset:
        truncate_table("root_causes", conn)

    # Row-by-row insert with error isolation
    cols = "anomaly_id, kpi_name, anomaly_date, status, dimension, segment_value, contribution_pct, segment_rank, analysed_at"
    sql  = (
        f"INSERT INTO root_causes ({cols}) VALUES %s "
        "ON CONFLICT (anomaly_id, segment_rank) DO NOTHING"
    )

    from psycopg2.extras import execute_values
    failed = 0
    inserted = 0
    try:
        with conn.cursor() as cur:
            execute_values(cur, sql, insert_rows)
            inserted = cur.rowcount
    except Exception as bulk_err:
        logger.warning(f"  bulk insert failed ({bulk_err}), switching to row-by-row")
        # The failed bulk insert left the transaction aborted; roll back first
        # or every row below would fail with "current transaction is aborted".
        conn.rollback()
        # Commit each row individually so a later row's failure/rollback can't
        # erase rows that already succeeded in this loop.
        inserted = 0
        for idx, r in enumerate(insert_rows):
            try:
                with conn.cursor() as cur:
                    execute_values(cur, sql, [r])
                conn.commit()
                inserted += 1
            except Exception as row_err:
                conn.rollback()
                logger.error(f"  row {idx} failed: {row_err}")
                logger.error(f"  bad row: {r}")
                logger.error(f"  bad types: {[type(v).__name__ for v in r]}")
                failed += 1

    logger.info(f"  inserted {inserted}, failed {failed}")
    _log_step("root_causes", inserted)
    return inserted

# ── llm_calls ─────────────────────────────────────────────────────────────────

def migrate_llm_calls(conn, reset: bool = False) -> int:
    jsonl_path = ROOT / "data" / "monitoring" / "llm_calls.jsonl"
    if not jsonl_path.exists():
        logger.warning("llm_calls.jsonl not found, skipping")
        return 0

    logger.info("Loading LLM call log...")
    records = []
    with open(jsonl_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    df = pd.DataFrame(records)
    df["called_at"] = pd.to_datetime(df["timestamp"])
    df["loaded_at"] = datetime.now()

    if "cost_usd" in df.columns:
        df = df.rename(columns={"cost_usd": "estimated_cost_usd"})
    elif "estimated_cost_usd" not in df.columns:
        df["estimated_cost_usd"] = 0.0

    df["quality_flags"] = df.get("quality_flags", pd.Series([[] for _ in range(len(df))])).apply(
        lambda x: x if isinstance(x, list) else []
    )
    for col in ["input_tokens", "output_tokens", "latency_ms"]:
        if col not in df.columns:
            df[col] = None

    if "anomaly_date" in df.columns:
        df["anomaly_date"] = pd.to_datetime(df["anomaly_date"], errors="coerce")
        df["anomaly_date"] = df["anomaly_date"].where(df["anomaly_date"].notna(), None)
    else:
        df["anomaly_date"] = None

    df["success"] = df.get("success", True)

    cols = ["called_at", "model", "prompt_version", "kpi_name", "anomaly_date",
            "input_tokens", "output_tokens", "estimated_cost_usd",
            "latency_ms", "success", "quality_flags", "loaded_at"]

    # llm_calls.jsonl is the append-only source of truth and this table has
    # no reliable natural key (timestamp granularity isn't guaranteed unique),
    # so always truncate and fully reload rather than risk re-appending the
    # entire call history on every run.
    truncate_table("llm_calls", conn)

    n = insert_dataframe(df[cols], "llm_calls", conn, conflict_action="DO NOTHING")
    _log_step("llm_calls", n)
    return n


# ── narratives ────────────────────────────────────────────────────────────────

def migrate_narratives(conn, reset: bool = False) -> int:
    sources = [
        (ROOT / "data" / "insights" / "narratives.json",     "standard"),
        (ROOT / "data" / "insights" / "rag_narratives.json", "rag"),
    ]

    if reset:
        truncate_table("narratives", conn)

    total = 0
    for path, narrative_type in sources:
        if not path.exists():
            logger.warning(f"{path.name} not found, skipping")
            continue

        logger.info(f"Loading {narrative_type} narratives from {path.name}...")
        with open(path, "r") as f:
            data = json.load(f)

        # Handle both list and dict formats
        if isinstance(data, dict):
            data = list(data.values())

        rows = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            # Skip entries with no valid date
            raw_date = entry.get("anomaly_date") or entry.get("date")
            if not raw_date or str(raw_date) in ("NaT", "nan", "None", ""):
                continue
            try:
                anomaly_date = pd.to_datetime(raw_date)
            except Exception:
                continue

            narrative_text = entry.get("narrative") or entry.get("narrative_text") or ""
            if not narrative_text:
                continue

            prompt_version = entry.get("prompt_version", "unknown")
            generated_at = entry.get("generated_at")
            if not generated_at or str(generated_at) in ("NaT", "nan", "None", ""):
                generated_at = datetime.now().isoformat()

            retrieved = entry.get("retrieved_context")
            rows.append({
                "kpi_name":          entry.get("kpi_name"),
                "anomaly_date":      anomaly_date,
                "narrative_type":    narrative_type,
                "prompt_version":    prompt_version,
                "narrative_text":    narrative_text,
                "retrieved_context": json.dumps(retrieved) if retrieved else None,
                "generated_at":      generated_at,
            })

        if not rows:
            logger.warning(f"  No valid rows in {path.name}")
            continue

        result_df = pd.DataFrame(rows)
        result_df = result_df.drop_duplicates(
            subset=["kpi_name", "anomaly_date", "narrative_type"], keep="last"
        )

        n = upsert_dataframe(
            result_df, "narratives",
            conflict_columns=["kpi_name", "anomaly_date", "narrative_type"],
            update_columns=["narrative_text", "prompt_version", "generated_at"],
            conn=conn
        )
        _log_step(f"narratives ({narrative_type})", n)
        total += n

    return total


# ── main ──────────────────────────────────────────────────────────────────────

def run(reset: bool = False) -> None:
    logger.info("=" * 55)
    logger.info("  E-Commerce Analytics — Phase 7 Migration")
    logger.info("=" * 55)

    if reset:
        logger.warning("  --reset: all tables will be truncated first")

    steps = [
        ("raw_transactions", migrate_raw_transactions),
        ("kpi_results",      migrate_kpi_results),
        ("anomalies",        migrate_anomalies),
        ("root_causes",      migrate_root_causes),
        ("llm_calls",        migrate_llm_calls),
        ("narratives",       migrate_narratives),
    ]

    totals = {}
    for name, fn in steps:
        try:
            with get_connection() as conn:
                totals[name] = fn(conn, reset)
        except Exception as e:
            logger.error(f"  Step '{name}' failed: {e}")
            totals[name] = -1

    logger.info("=" * 55)
    logger.info("  Migration complete. Summary:")
    for table, n in totals.items():
        status = f"{n:>8,} rows" if n >= 0 else "    FAILED"
        logger.info(f"    {table:<30} {status}")
    logger.info("=" * 55)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true",
                        help="Truncate all tables before loading")
    args = parser.parse_args()
    run(reset=args.reset)