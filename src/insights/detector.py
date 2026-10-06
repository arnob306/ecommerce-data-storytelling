"""
Anomaly Detection Engine - orchestrates statistical detection across all KPIs.

This module:
  1. Generates time-series KPI data (daily/weekly) from raw transactions
  2. Runs Z-score, IQR, and Mann-Kendall detection across all KPIs
  3. Deduplicates overlapping detections and merges confidence scores
  4. Saves results to data/insights/anomalies.csv for Week 5 consumption

Design decision: the three methods are intentionally run independently and
then merged, rather than trying to build one combined test. This makes each
method's output inspectable and the deduplication logic explicit.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging

from src.kpis.engine import KPIEngine
from src.data.ingestion import DataLoader
from src.insights.models import Anomaly
from src.insights.methods import (
    detect_zscore_anomalies,
    detect_iqr_anomalies,
    detect_trend_anomalies
)

logger = logging.getLogger(__name__)


# KPIs that are ratios/percentages — their expected ranges are different
# from volume metrics and we interpret their anomalies differently
RATIO_KPIS = {
    'repeat_customer_rate',
    'product_return_rate',
    'international_revenue_share',
    'weekend_revenue_share',
    'peak_hour_concentration',
    'product_revenue_concentration'
}

SKIP_KPIS = {'new_customers', 'revenue_by_country'}


class AnomalyDetector:
    """
    Detects anomalies in KPI time series using multiple statistical methods.

    Workflow:
      1. generate_kpi_timeseries() — runs KPI engine per time window
      2. detect_all() — runs all three methods across all KPIs
      3. merge_detections() — deduplicates and boosts confidence when methods agree
      4. save_anomalies() — persists results for Week 5

    The baseline_window parameter allows excluding known seasonal periods
    (e.g. Christmas) from the baseline calculation, which prevents extreme
    seasonal values from distorting what counts as "normal".
    """

    def __init__(
        self,
        config_path: str = "config/kpis.yaml",
        zscore_threshold: float = 2.5,
        iqr_multiplier: float = 1.5,
        trend_significance: float = 0.05,
        baseline_window: Optional[Tuple[str, str]] = None
    ):
        """
        Initialise detector with configurable thresholds.

        Args:
            config_path: Path to KPI config
            zscore_threshold: Z-score magnitude to flag (default 2.5)
            iqr_multiplier: IQR fence multiplier (default 1.5)
            trend_significance: p-value for Mann-Kendall (default 0.05)
            baseline_window: Optional (start_date, end_date) tuple to restrict
                           the baseline period. Dates as 'YYYY-MM-DD' strings.
                           Points outside this window are still analysed but
                           the baseline stats are computed only within it.
        """
        self.engine = KPIEngine(config_path)
        self.zscore_threshold = zscore_threshold
        self.iqr_multiplier = iqr_multiplier
        self.trend_significance = trend_significance
        self.baseline_window = baseline_window
        self.anomalies: List[Anomaly] = []

    def generate_kpi_timeseries(
        self,
        df: pd.DataFrame,
        window: str = 'W'
    ) -> pd.DataFrame:
        """
        Calculate KPIs for each time window to produce a time series.

        Args:
            df: Raw transaction DataFrame
            window: 'W' for weekly (recommended given 13 months of data),
                   'D' for daily (noisier, more data points)

        Returns:
            DataFrame with one row per time period and one column per KPI.
            Shape: (~52 rows x 16 columns) for weekly on 13 months of data.

        Why weekly over daily:
            Daily KPI data on 13 months gives ~365 points but is very noisy —
            individual days can vary hugely based on day-of-week effects.
            Weekly smooths this while still giving ~52 points for detection.
            Mann-Kendall needs at least 10 points, so weekly is the minimum
            sensible cadence for this dataset.
        """
        logger.info(f"Generating KPI time series with {window} window...")
        ts_df = self.engine.calculate_by_time_window(df, window=window)
        
        if 'date' in ts_df.columns:
            ts_df['date'] = pd.to_datetime(ts_df['date'])
            ts_df = ts_df.set_index('date')
        
        logger.info(f"Generated {len(ts_df)} time periods x {len(ts_df.columns)} columns")
        return ts_df

    def _get_baseline(self, series: pd.Series) -> pd.Series:
        """Return the baseline series for computing expected values."""
        if self.baseline_window is None:
            return series

        try:
            # Convert string dates to pandas Timestamp objects for comparison
            start = pd.to_datetime(self.baseline_window[0])
            end = pd.to_datetime(self.baseline_window[1])
            
            # Create the mask and filter the series
            mask = (series.index >= start) & (series.index <= end)
            baseline = series[mask]

            if len(baseline) < 5:
                logger.warning("Baseline window too narrow, falling back to full series")
                return series

            return baseline

        except Exception as e:
            logger.warning(f"Error filtering baseline: {e}. Falling back to full series.")
            return series

    def detect_all(self, ts_df: pd.DataFrame) -> List[Anomaly]:
        """
        Run all three detection methods across all KPIs.

        Args:
            ts_df: Time-series DataFrame from generate_kpi_timeseries()

        Returns:
            Merged, deduplicated list of Anomaly objects sorted by date.
        """
        all_anomalies = []

        kpi_columns = [
            col for col in ts_df.columns
            if col != 'date' and col not in SKIP_KPIS
        ]

        logger.info(f"Running anomaly detection on {len(kpi_columns)} KPIs...")

        for kpi_name in kpi_columns:
            if kpi_name not in ts_df.columns:
                continue

            series = ts_df[kpi_name].dropna()

            if len(series) < 7:
                logger.warning(f"Skipping {kpi_name} — insufficient data points ({len(series)})")
                continue

            baseline = self._get_baseline(series)

            # Run all three methods
            zscore_anomalies = detect_zscore_anomalies(
                series, kpi_name,
                threshold=self.zscore_threshold,
                baseline_series=baseline
            )

            iqr_anomalies = detect_iqr_anomalies(
                series, kpi_name,
                fence_multiplier=self.iqr_multiplier,
                baseline_series=baseline
            )

            trend_anomalies = detect_trend_anomalies(
                series, kpi_name,
                significance_level=self.trend_significance
            )

            kpi_anomalies = zscore_anomalies + iqr_anomalies + trend_anomalies
            logger.info(
                f"{kpi_name}: {len(zscore_anomalies)} zscore, "
                f"{len(iqr_anomalies)} IQR, "
                f"{len(trend_anomalies)} trend anomalies"
            )

            all_anomalies.extend(kpi_anomalies)

        # Merge overlapping detections — when multiple methods flag the same
        # KPI on the same date, combine them into one higher-confidence anomaly
        merged = self._merge_detections(all_anomalies)
        merged.sort(key=lambda a: (a.date, a.kpi_name))

        self.anomalies = merged
        logger.info(f"Total anomalies after merging: {len(merged)}")
        return merged

    def _merge_detections(self, anomalies: List[Anomaly]) -> List[Anomaly]:
        """
        Merge anomalies where multiple methods agree on the same KPI + date.

        When Z-score and IQR both flag the same point, that's stronger evidence
        than either alone. We keep one anomaly but boost its confidence and
        record that multiple methods agreed.

        Mann-Kendall detections are kept separately — they represent a different
        type of finding (trend vs point anomaly) and shouldn't be merged with
        point detections even if they share a date.
        """
        # Separate point anomalies from trend anomalies
        point_anomalies = [a for a in anomalies if a.method != 'mann_kendall']
        trend_anomalies = [a for a in anomalies if a.method == 'mann_kendall']

        # Group point anomalies by (kpi_name, date)
        groups: Dict[Tuple, List[Anomaly]] = {}
        for anomaly in point_anomalies:
            # Round date to day for grouping (weekly series won't have sub-day variation)
            key = (anomaly.kpi_name, anomaly.date.date())
            if key not in groups:
                groups[key] = []
            groups[key].append(anomaly)

        merged = []
        for (kpi_name, date), group in groups.items():
            if len(group) == 1:
                merged.append(group[0])
            else:
                primary = max(group, key=lambda a: a.confidence)
                methods_agreed = [a.method for a in group]

                # Confidence boost: each additional agreeing method adds 0.1,
                # capped at 0.99
                boosted_confidence = min(0.99, primary.confidence + 0.1 * (len(group) - 1))

                # Create merged anomaly with boosted confidence and updated description
                merged_anomaly = Anomaly(
                    kpi_name=primary.kpi_name,
                    date=primary.date,
                    actual_value=primary.actual_value,
                    expected_value=primary.expected_value,
                    deviation=primary.deviation,
                    deviation_pct=primary.deviation_pct,
                    method=f"{'_and_'.join(methods_agreed)}",
                    severity=primary.severity,
                    confidence=round(boosted_confidence, 3),
                    stat_value=primary.stat_value,
                    description=(
                        f"{primary.description} "
                        f"[Confirmed by {len(group)} methods: {', '.join(methods_agreed)}]"
                    )
                )
                merged.append(merged_anomaly)

        # Add trend anomalies unchanged
        merged.extend(trend_anomalies)
        return merged


    def save_anomalies(
        self,
        anomalies: List[Anomaly],
        output_path: str = "data/insights/anomalies.csv"
    ):
        """Save anomalies to CSV for Week 5 root cause analysis."""
        if not anomalies:
            logger.warning("No anomalies to save")
            return

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        df = pd.DataFrame([a.to_dict() for a in anomalies])
        df.to_csv(output_file, index=False)
        logger.info(f"Saved {len(anomalies)} anomalies to {output_file}")

    def print_summary(self, anomalies: List[Anomaly]):
        """Print a readable summary of detected anomalies."""
        if not anomalies:
            print("No anomalies detected.")
            return

        print("\n" + "="*70)
        print("ANOMALY DETECTION RESULTS")
        print("="*70)
        print(f"Detection Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Total Anomalies Detected: {len(anomalies)}")
        print("="*70)

        # Summary by severity
        by_severity = {}
        for a in anomalies:
            by_severity.setdefault(a.severity, []).append(a)

        print("\nBy Severity:")
        for severity in ['critical', 'high', 'medium', 'low']:
            count = len(by_severity.get(severity, []))
            if count:
                print(f"  {severity.upper():.<20} {count}")

        # Summary by KPI
        print("\nBy KPI:")
        by_kpi = {}
        for a in anomalies:
            by_kpi.setdefault(a.kpi_name, []).append(a)

        for kpi, kpi_anomalies in sorted(by_kpi.items()):
            print(f"  {kpi:.<45} {len(kpi_anomalies)} anomalies")

        # Top 10 highest confidence anomalies
        print("\nTop 10 Highest Confidence Anomalies:")
        print("-"*70)
        top = sorted(anomalies, key=lambda a: a.confidence, reverse=True)[:10]
        for a in top:
            print(f"\n  [{a.severity.upper()}] {a.kpi_name} — {a.date.strftime('%Y-%m-%d')}")
            print(f"  {a.description}")
            print(f"  Confidence: {a.confidence:.0%} | Method: {a.method}")

        print("\n" + "="*70)

def main():
    """Run anomaly detection on the full UK retail dataset."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s:%(name)s:%(message)s'
    )

    # Load data
    logger.info("Loading transaction data...")
    loader = DataLoader()
    df = loader.load_retail_data()

    detector = AnomalyDetector(
        zscore_threshold=2.5,
        iqr_multiplier=1.5,
        trend_significance=0.05,
        baseline_window=('2011-01-01', '2011-11-30')
    )

    ts_df = detector.generate_kpi_timeseries(df, window='W')

    anomalies = detector.detect_all(ts_df)

    detector.print_summary(anomalies)
    detector.save_anomalies(anomalies)

    print(f"\nResults saved to: data/insights/anomalies.csv")
    print(f"Total anomalies: {len(anomalies)}")
    print("\nReady for Week 5: Root Cause Analysis")


if __name__ == "__main__":
    main()