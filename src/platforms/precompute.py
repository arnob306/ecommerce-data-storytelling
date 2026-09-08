"""
Pre-computation script for Phase 6 dashboard.

Runs once to generate and cache all data the dashboard needs.
Saves to parquet files so the dashboard loads in milliseconds
rather than rerunning the full pipeline on every page load.

Run this before launching the dashboard:
    python -m src.platform.precompute

Output files:
    data/cache/kpi_timeseries.parquet   - 53 weekly KPI values
    data/cache/kpi_latest.parquet       - single-row latest KPI values
    data/cache/anomalies.parquet        - 47 anomalies from Phase 4
    data/cache/root_causes.parquet      - 39 root cause results from Phase 5
"""

import pandas as pd
from pathlib import Path
import logging

from src.data.ingestion import DataLoader
from src.kpis.engine import KPIEngine
from src.insights.detector import AnomalyDetector
from src.insights.analyser import RootCauseAnalyser

logger = logging.getLogger(__name__)

CACHE_DIR = Path('data/cache')


def precompute_all():
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s:%(name)s:%(message)s'
    )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info('Loading transaction data...')
    loader = DataLoader()
    df = loader.load_retail_data()
    logger.info('Computing KPI time series...')
    engine = KPIEngine()
    ts_df = engine.calculate_by_time_window(df, window='W')
    ts_df['date'] = pd.to_datetime(ts_df['date'])
    ts_df = ts_df.set_index('date')
    ts_df.index.name = 'week_date'
    ts_df.to_parquet(CACHE_DIR / 'kpi_timeseries.parquet', index=True)
    logger.info(f'Saved KPI time series: {ts_df.shape}')
    logger.info('Computing latest KPI values...')
    latest = engine.calculate_all(df)
    latest_df = pd.DataFrame([latest])
    latest_df.to_parquet(CACHE_DIR / 'kpi_latest.parquet', index=False)
    logger.info('Saved latest KPI values')

    # --- Anomalies ---
    anomalies_src = Path('data/insights/anomalies.csv')
    if anomalies_src.exists():
        logger.info('Loading anomalies from Phase 4...')
        anomalies_df = pd.read_csv(anomalies_src)
        anomalies_df['date'] = pd.to_datetime(anomalies_df['date'])
        anomalies_df.to_parquet(CACHE_DIR / 'anomalies.parquet', index=False)
        logger.info(f'Saved {len(anomalies_df)} anomalies')
    else:
        logger.warning('anomalies.csv not found - run Phase 4 first')

    # --- Root causes ---
    root_causes_src = Path('data/insights/root_causes.csv')
    if root_causes_src.exists():
        logger.info('Loading root causes from Phase 5...')
        rc_df = pd.read_csv(root_causes_src)
        rc_df['date'] = pd.to_datetime(rc_df['date'])
        rc_df.to_parquet(CACHE_DIR / 'root_causes.parquet', index=False)
        logger.info(f'Saved {len(rc_df)} root cause results')
    else:
        logger.warning('root_causes.csv not found - run Phase 5 first')

    logger.info('Pre-computation complete. Dashboard is ready to launch.')
    print('\nCache files written to data/cache/:')
    for f in sorted(CACHE_DIR.glob('*.parquet')):
        size_kb = f.stat().st_size / 1024
        print(f'  {f.name:<40} {size_kb:.1f} KB')
    print('\nRun the dashboard with:')
    print('  streamlit run src/platforms/dashboard.py')


if __name__ == '__main__':
    precompute_all()