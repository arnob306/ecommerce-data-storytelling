"""
Root Cause Analysis Engine - explains what is driving each detected anomaly.

For each anomaly from Phase 4, this module:
  1. Filters raw transaction data to the anomaly time window
  2. Slices the data by available dimensions (Country, StockCode, HourOfDay)
  3. Calculates each segment's contribution to the total deviation
  4. Ranks segments by impact and produces structured RootCauseResult objects
  5. Saves results to data/insights/root_causes.csv

Design decision: root cause analysis works directly on raw transaction data,
not on pre-aggregated KPI results. This gives us the dimensional granularity
needed to identify which specific country, product, or time period is driving
a metric change. The tradeoff is it's slower, but correctness matters more
here than speed.

Limitation: ratio KPIs (repeat_customer_rate, product_return_rate, etc.)
cannot be directly segmented because their numerator and denominator need
to be computed separately per segment. These are flagged for manual review
rather than producing potentially misleading results.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Tuple
import logging

from src.data.ingestion import DataLoader
from src.insights.models import Anomaly
from src.insights.results import RootCauseResult, SegmentContribution

logger = logging.getLogger(__name__)


# KPIs where direct dimensional slicing is meaningful.
# These all reduce to sum(Quantity * UnitPrice) or a count,
# so we can filter by segment and recalculate directly.
# KPIs where direct dimensional slicing is meaningful.
# These all reduce to sum(Quantity * UnitPrice) or a count,
# so we can filter by segment and recalculate directly.
SLICEABLE_KPIS = {
    'total_revenue',
    'order_count',
    'units_sold',
    'active_customers',
}

# Ratio KPIs that require separate numerator/denominator calculation per segment.
# Slicing these naively produces misleading results so we flag for manual review.
RATIO_KPIS = {
    'repeat_customer_rate',
    'product_return_rate',
    'international_revenue_share',
    'weekend_revenue_share',
    'peak_hour_concentration',
    'product_revenue_concentration',
    'avg_unit_price',          # Moved from SLICEABLE
    'revenue_per_order',       # Moved from SLICEABLE
    'revenue_per_customer',    # Moved from SLICEABLE
    'items_per_order',         # Moved from SLICEABLE
}

# Dimensions to slice by and their corresponding raw data columns
DIMENSIONS = {
    'Country': 'Country',
    'StockCode': 'StockCode',
    'HourOfDay': None,   # derived from InvoiceDate
}

# For StockCode, limit to top N to avoid noise from 4,070 unique products
TOP_N_PRODUCTS = 20


class RootCauseAnalyser:
    """
    Analyses root causes of detected anomalies by dimensional slicing.

    Workflow:
      1. Load anomalies from anomalies.csv
      2. For each anomaly, filter raw data to the anomaly week
      3. Determine the baseline period for that KPI
      4. Slice by each dimension and compute segment contributions
      5. Rank and store results
    """

    def __init__(self, baseline_window: Optional[Tuple[str, str]] = None):
        """
        Initialise analyser.

        Args:
            baseline_window: Optional (start, end) date strings to define
                           the normal baseline period. Same window used in
                           Phase 4 detector for consistency.
        """
        self.baseline_window = baseline_window
        self.results: List[RootCauseResult] = []

    # =========================================================================
    # DATA PREPARATION
    # =========================================================================

    def _add_derived_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add HourOfDay column derived from InvoiceDate."""
        df = df.copy()
        if 'HourOfDay' not in df.columns:
            df['HourOfDay'] = df['InvoiceDate'].dt.hour
        if 'TransactionValue' not in df.columns:
            df['TransactionValue'] = df['Quantity'] * df['UnitPrice']
        return df

    def _get_period_data(
        self,
        df: pd.DataFrame,
        anomaly_date: datetime,
        window: str = 'W'
    ) -> pd.DataFrame:
        """
        Filter raw data to the anomaly time window.

        For weekly anomalies, returns the 7 days ending on the anomaly date.
        This matches how calculate_by_time_window groups data in the engine.

        Args:
            df: Full raw transaction DataFrame
            anomaly_date: The anomaly date (week end date from detector)
            window: Time window size - 'W' for weekly

        Returns:
            Filtered DataFrame for the anomaly period
        """
        if window == 'W':
            period_end = anomaly_date
            period_start = anomaly_date - timedelta(days=6)
        else:
            period_start = anomaly_date
            period_end = anomaly_date

        mask = (
            (df['InvoiceDate'] >= period_start) &
            (df['InvoiceDate'] <= period_end)
        )
        return df[mask]

    def _get_baseline_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Filter raw data to the baseline period.

        Uses the same baseline_window as Phase 4 for consistency.
        If no window is set, uses the full dataset as baseline.
        """
        if self.baseline_window is None:
            return df

        start, end = self.baseline_window
        mask = (
            (df['InvoiceDate'] >= pd.Timestamp(start)) &
            (df['InvoiceDate'] <= pd.Timestamp(end))
        )
        baseline = df[mask]

        if len(baseline) == 0:
            logger.warning('Baseline window returned no data, using full dataset')
            return df

        return baseline

    # =========================================================================
    # METRIC CALCULATION PER SEGMENT
    # =========================================================================

    def _calculate_metric_for_segment(
        self,
        df: pd.DataFrame,
        kpi_name: str,
        dimension: str,
        segment_value
    ) -> float:
        """
        Calculate a KPI value for a specific segment of the data.

        Filters df to rows where dimension == segment_value,
        then computes the relevant metric.

        For revenue: sum(Quantity * UnitPrice)
        For orders: count(distinct InvoiceNo)
        For customers: count(distinct CustomerID)
        For units: sum(Quantity)
        For derived ratios: compute numerator and denominator separately
        """
        if dimension == 'HourOfDay':
            segment_df = df[df['HourOfDay'] == segment_value]
        else:
            segment_df = df[df[dimension] == segment_value]

        if len(segment_df) == 0:
            return 0.0

        if kpi_name in ('total_revenue', 'revenue_per_order',
                        'revenue_per_customer', 'avg_unit_price'):
            return float((segment_df['Quantity'] * segment_df['UnitPrice']).sum())

        elif kpi_name == 'order_count':
            return float(segment_df['InvoiceNo'].nunique())

        elif kpi_name == 'units_sold':
            return float(segment_df['Quantity'].sum())

        elif kpi_name == 'active_customers':
            return float(segment_df['CustomerID'].nunique())

        elif kpi_name == 'items_per_order':
            orders = segment_df['InvoiceNo'].nunique()
            return float(segment_df['Quantity'].sum() / orders) if orders > 0 else 0.0

        else:
            # Default: revenue
            return float((segment_df['Quantity'] * segment_df['UnitPrice']).sum())

    # =========================================================================
    # DIMENSION SLICING
    # =========================================================================

    def _analyse_dimension(
        self,
        period_df: pd.DataFrame,
        baseline_df: pd.DataFrame,
        kpi_name: str,
        dimension: str,
        total_deviation: float
    ) -> List[SegmentContribution]:
        """
        Slice data by one dimension and compute each segment's contribution.

        For each unique value of the dimension (e.g. each Country):
          1. Calculate the metric in the anomaly period
          2. Calculate the expected metric from the baseline
             (scaled to match the anomaly period length)
          3. Compute deviation = actual - expected
          4. Compute contribution = deviation / total_deviation

        Returns segments sorted by absolute contribution, descending.

        Args:
            period_df: Data for the anomaly week
            baseline_df: Data for the baseline period
            kpi_name: Which KPI we're explaining
            dimension: Which dimension to slice by
            total_deviation: Total anomaly deviation for normalisation
        """
        if total_deviation == 0:
            return []

        # Get column name for this dimension
        col = DIMENSIONS.get(dimension)

        # Get unique segment values - limit products to top N by baseline revenue
        if dimension == 'StockCode':
            top_products = (
                (baseline_df['Quantity'] * baseline_df['UnitPrice'])
                .groupby(baseline_df['StockCode'])
                .sum()
                .nlargest(TOP_N_PRODUCTS)
                .index.tolist()
            )
            segments = top_products
        elif dimension == 'HourOfDay':
            segments = sorted(baseline_df['HourOfDay'].unique())
        else:
            segments = baseline_df[dimension].unique().tolist()

        # Scale factor: baseline covers a longer period than the anomaly week.
        # To make expected values comparable to actual (one week), we scale
        # baseline values down proportionally.
        baseline_days = (
            baseline_df['InvoiceDate'].max() - baseline_df['InvoiceDate'].min()
        ).days + 1
        period_days = 7  # weekly window
        scale = period_days / baseline_days if baseline_days > 0 else 1.0

        contributions = []

        for seg_val in segments:
            actual = self._calculate_metric_for_segment(
                period_df, kpi_name, dimension, seg_val
            )
            baseline_raw = self._calculate_metric_for_segment(
                baseline_df, kpi_name, dimension, seg_val
            )
            expected = baseline_raw * scale
            deviation = actual - expected
            contribution_pct = (deviation / total_deviation) * 100

            # Only include segments with meaningful contribution (>2%)
            if abs(contribution_pct) >= 2.0:
                contributions.append(SegmentContribution(
                    dimension=dimension,
                    segment_value=str(seg_val),
                    actual_value=round(actual, 2),
                    expected_value=round(expected, 2),
                    deviation=round(deviation, 2),
                    contribution_pct=round(contribution_pct, 1)
                ))

        # Sort by absolute contribution descending
        contributions.sort(key=lambda x: abs(x.contribution_pct), reverse=True)
        return contributions

    def analyse_anomaly(
        self,
        anomaly: Anomaly,
        df: pd.DataFrame
    ) -> RootCauseResult:
        """
        Run root cause analysis for a single anomaly.

        Args:
            anomaly: Anomaly object from Phase 4
            df: Full raw transaction DataFrame

        Returns:
            RootCauseResult with ranked segment contributions
        """
        logger.info(f'Analysing root cause for {anomaly.kpi_name} on {anomaly.date}')

        # Ratio KPIs cannot be directly segmented
        if anomaly.kpi_name in RATIO_KPIS:
            logger.info(f'Skipping {anomaly.kpi_name} - ratio KPI, flagging for manual review')
            return RootCauseResult(
                kpi_name=anomaly.kpi_name,
                date=anomaly.date,
                anomaly_severity=anomaly.severity,
                anomaly_confidence=anomaly.confidence,
                total_deviation=anomaly.deviation,
                total_deviation_pct=anomaly.deviation_pct,
                status='manual_review_required'
            )

        # Add derived columns
        df = self._add_derived_columns(df)

        # Get period and baseline data
        period_df = self._get_period_data(df, anomaly.date)
        baseline_df = self._get_baseline_data(df)

        if len(period_df) == 0:
            logger.warning(f'No data found for anomaly period: {anomaly.date}')
            return RootCauseResult(
                kpi_name=anomaly.kpi_name,
                date=anomaly.date,
                anomaly_severity=anomaly.severity,
                anomaly_confidence=anomaly.confidence,
                total_deviation=anomaly.deviation,
                total_deviation_pct=anomaly.deviation_pct,
                status='insufficient_data'
            )

        # Analyse each dimension
        all_contributions = []
        dimensions_analysed = []

        for dimension in DIMENSIONS.keys():
            contributions = self._analyse_dimension(
                period_df=period_df,
                baseline_df=baseline_df,
                kpi_name=anomaly.kpi_name,
                dimension=dimension,
                total_deviation=anomaly.deviation
            )
            if contributions:
                all_contributions.extend(contributions[:5])  # top 5 per dimension
                dimensions_analysed.append(dimension)

        # Sort all contributions by absolute contribution across all dimensions
        all_contributions.sort(key=lambda x: abs(x.contribution_pct), reverse=True)

        return RootCauseResult(
            kpi_name=anomaly.kpi_name,
            date=anomaly.date,
            anomaly_severity=anomaly.severity,
            anomaly_confidence=anomaly.confidence,
            total_deviation=anomaly.deviation,
            total_deviation_pct=anomaly.deviation_pct,
            top_segments=all_contributions[:10],  # top 10 overall
            dimensions_analysed=dimensions_analysed,
            status='analysed'
        )

    def analyse_all(
        self,
        anomalies: List[Anomaly],
        df: pd.DataFrame
    ) -> List[RootCauseResult]:
        """
        Run root cause analysis across all anomalies.

        Skips Mann-Kendall trend anomalies - trends are driven by the whole
        period rather than a single week, so dimensional slicing on one week
        doesn't explain a multi-month trend meaningfully.

        Args:
            anomalies: List of Anomaly objects from Phase 4
            df: Full raw transaction DataFrame

        Returns:
            List of RootCauseResult objects
        """
        results = []

        # Filter to point anomalies only - skip pure trend detections
        point_anomalies = [
            a for a in anomalies
            if 'mann_kendall' not in a.method
        ]
        trend_only = [
            a for a in anomalies
            if a.method == 'mann_kendall'
        ]

        logger.info(
            f'Analysing {len(point_anomalies)} point anomalies '
            f'(skipping {len(trend_only)} trend-only detections)'
        )

        for anomaly in point_anomalies:
            result = self.analyse_anomaly(anomaly, df)
            results.append(result)

        self.results = results
        logger.info(f'Root cause analysis complete: {len(results)} results')
        return results

    # =========================================================================
    # OUTPUT
    # =========================================================================

    def save_results(
        self,
        results: List[RootCauseResult],
        output_path: str = 'data/insights/root_causes.csv'
    ):
        """Save root cause results to CSV."""
        if not results:
            logger.warning('No results to save')
            return

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        rows = [r.to_dict() for r in results]
        df = pd.DataFrame(rows)
        df.to_csv(output_file, index=False)
        logger.info(f'Saved {len(results)} root cause results to {output_file}')

    def print_summary(self, results: List[RootCauseResult]):
        """Print a readable summary of root cause findings."""
        if not results:
            print('No results to display.')
            return

        print('\n' + '='*70)
        print('ROOT CAUSE ANALYSIS RESULTS')
        print('='*70)
        print(f'Analysis Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        print(f'Total Anomalies Analysed: {len(results)}')

        analysed = [r for r in results if r.status == 'analysed']
        manual = [r for r in results if r.status == 'manual_review_required']
        insufficient = [r for r in results if r.status == 'insufficient_data']

        print(f'  Successfully explained: {len(analysed)}')
        print(f'  Manual review required: {len(manual)}')
        print(f'  Insufficient data: {len(insufficient)}')
        print('='*70)

        # Print top findings - highest confidence anomalies that were explained
        top_results = sorted(
            analysed,
            key=lambda r: r.anomaly_confidence,
            reverse=True
        )[:10]

        print('\nTop Findings (highest confidence anomalies explained):')
        print('-'*70)

        for r in top_results:
            print(f'\n  [{r.anomaly_severity.upper()}] {r.kpi_name} - {r.date.strftime("%Y-%m-%d")}')
            print(f'  {r.summary}')

            if r.top_segments:
                print(f'  Top drivers:')
                for seg in r.top_segments[:3]:
                    direction = 'above' if seg.deviation > 0 else 'below'
                    print(
                        f'    - {seg.dimension}={seg.segment_value}: '
                        f'{seg.contribution_pct:.1f}% of deviation '
                        f'({direction} expected by {abs(seg.deviation):,.0f})'
                    )

        print('\n' + '='*70)


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run root cause analysis on all Phase 4 anomalies."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s:%(name)s:%(message)s'
    )

    # Load raw data
    logger.info('Loading transaction data...')
    loader = DataLoader()
    df = loader.load_retail_data()

    # Load anomalies from Phase 4
    anomalies_path = Path('data/insights/anomalies.csv')
    if not anomalies_path.exists():
        print('ERROR: data/insights/anomalies.csv not found.')
        print('Run Phase 4 first: python -m src.insights.detector')
        return

    logger.info('Loading anomalies from Phase 4...')
    anomalies_df = pd.read_csv(anomalies_path)
    anomalies_df['date'] = pd.to_datetime(anomalies_df['date'])

    # Reconstruct Anomaly objects from CSV
    from src.insights.models import Anomaly
    anomalies = []
    for _, row in anomalies_df.iterrows():
        try:
            anomaly = Anomaly(
                kpi_name=row['kpi_name'],
                date=row['date'],
                actual_value=row['actual_value'],
                expected_value=row['expected_value'],
                deviation=row['deviation'],
                deviation_pct=row['deviation_pct'],
                method=row['method'],
                severity=row['severity'],
                confidence=row['confidence'],
                stat_value=row['stat_value'],
                description=row.get('description', '')
            )
            anomalies.append(anomaly)
        except Exception as e:
            logger.warning(f'Could not reconstruct anomaly row: {e}')

    logger.info(f'Loaded {len(anomalies)} anomalies')

    # Run root cause analysis
    analyser = RootCauseAnalyser(
        baseline_window=('2011-01-01', '2011-11-30')
    )
    results = analyser.analyse_all(anomalies, df)

    # Print and save
    analyser.print_summary(results)
    analyser.save_results(results)

    print(f'\nResults saved to: data/insights/root_causes.csv')
    print(f'Total results: {len(results)}')
    print('\nPhase 5 complete - ready for dashboard and narratives')


if __name__ == '__main__':
    main()