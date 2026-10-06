"""
Statistical detection methods for anomaly detection.

Each method is a standalone function that takes a pandas Series
(a single KPI over time) and returns a list of Anomaly objects.

Keeping methods separate from the orchestration logic in detector.py
makes them individually testable and easy to swap or extend.
"""

import pandas as pd
import numpy as np
from scipy import stats
from typing import List, Optional
import logging

from src.insights.models import (
    Anomaly,
    severity_from_zscore,
    severity_from_iqr,
    severity_from_trend
)

logger = logging.getLogger(__name__)


# =============================================================================
# Z-SCORE DETECTION
# =============================================================================

def detect_zscore_anomalies(
    series: pd.Series,
    kpi_name: str,
    threshold: float = 2.5,
    baseline_series: Optional[pd.Series] = None
) -> List[Anomaly]:
    """
    Detect anomalies using Z-score (standard deviations from mean).

    How it works:
      1. Calculate mean and std of the baseline (historical) series
      2. For each point, compute z = (value - mean) / std
      3. Flag points where |z| exceeds the threshold

    Args:
        series: Time-indexed KPI values to analyse
        kpi_name: Name of the KPI (for anomaly labelling)
        threshold: Z-score magnitude to flag (default 2.5 = top ~1.2% of normal dist)
        baseline_series: If provided, use this for mean/std instead of series itself.
                        Useful for excluding known seasonal periods from the baseline.

    Returns:
        List of Anomaly objects for each flagged point

    Limitation:
        Assumes the series is approximately normally distributed.
        For heavily skewed metrics (e.g. revenue with Christmas spike),
        the mean and std will be pulled by outliers, potentially missing
        real anomalies or generating false positives. Use IQR alongside this.
    """
    if len(series.dropna()) < 7:
        logger.warning(f"Z-score: {kpi_name} has fewer than 7 data points, skipping")
        return []

    # Use separate baseline if provided, otherwise use the series itself
    baseline = baseline_series if baseline_series is not None else series

    mean = baseline.mean()
    std = baseline.std()

    if std == 0:
        logger.warning(f"Z-score: {kpi_name} has zero variance, skipping")
        return []

    anomalies = []

    for date, value in series.items():
        if pd.isna(value):
            continue

        z = (value - mean) / std

        if abs(z) >= threshold:
            deviation = value - mean
            deviation_pct = (deviation / mean) * 100 if mean != 0 else 0

            # Confidence scales with how far beyond the threshold we are.
            # At exactly threshold z-score: 0.5 confidence.
            # At 2x threshold: ~0.9 confidence. Capped at 0.99.
            confidence = min(0.99, 0.5 + (abs(z) - threshold) * 0.15)

            anomalies.append(Anomaly(
                kpi_name=kpi_name,
                date=date,
                actual_value=float(value),
                expected_value=float(mean),
                deviation=float(deviation),
                deviation_pct=float(deviation_pct),
                method='zscore',
                severity=severity_from_zscore(z),
                confidence=round(confidence, 3),
                stat_value=round(float(z), 4)
            ))

    logger.debug(f"Z-score: found {len(anomalies)} anomalies in {kpi_name}")
    return anomalies


# =============================================================================
# IQR DETECTION
# =============================================================================

def detect_iqr_anomalies(
    series: pd.Series,
    kpi_name: str,
    fence_multiplier: float = 1.5,
    baseline_series: Optional[pd.Series] = None
) -> List[Anomaly]:
    """
    Detect anomalies using Interquartile Range (IQR) method.

    How it works:
      1. Calculate Q1, Q3, and IQR = Q3 - Q1 from baseline
      2. Lower fence = Q1 - (fence_multiplier * IQR)
      3. Upper fence = Q3 + (fence_multiplier * IQR)
      4. Flag points outside these fences

    Args:
        series: Time-indexed KPI values to analyse
        kpi_name: Name of the KPI
        fence_multiplier: How many IQRs beyond Q1/Q3 to set fences (default 1.5)
        baseline_series: Optional separate baseline for fence calculation

    Returns:
        List of Anomaly objects

    Why use this alongside Z-score:
        IQR is resistant to outliers — the fences are based on the middle 50%
        of the data, so extreme values don't distort the baseline the way they
        do with mean/std. Better for skewed distributions like revenue.
    """
    if len(series.dropna()) < 7:
        logger.warning(f"IQR: {kpi_name} has fewer than 7 data points, skipping")
        return []

    baseline = baseline_series if baseline_series is not None else series

    q1 = baseline.quantile(0.25)
    q3 = baseline.quantile(0.75)
    iqr = q3 - q1

    if iqr == 0:
        logger.warning(f"IQR: {kpi_name} has zero IQR, skipping")
        return []

    lower_fence = q1 - (fence_multiplier * iqr)
    upper_fence = q3 + (fence_multiplier * iqr)
    median = baseline.median()

    anomalies = []

    for date, value in series.items():
        if pd.isna(value):
            continue

        if value < lower_fence or value > upper_fence:
            # How many IQRs beyond the fence is this point?
            if value > upper_fence:
                distance = (value - upper_fence) / iqr
            else:
                distance = (lower_fence - value) / iqr

            # Actual multiplier for severity classification
            actual_multiplier = fence_multiplier + distance

            deviation = value - median
            deviation_pct = (deviation / median) * 100 if median != 0 else 0

            # Confidence based on how far outside the fence we are
            confidence = min(0.99, 0.5 + distance * 0.2)

            anomalies.append(Anomaly(
                kpi_name=kpi_name,
                date=date,
                actual_value=float(value),
                expected_value=float(median),
                deviation=float(deviation),
                deviation_pct=float(deviation_pct),
                method='iqr',
                severity=severity_from_iqr(actual_multiplier),
                confidence=round(confidence, 3),
                stat_value=round(float(actual_multiplier), 4)
            ))

    logger.debug(f"IQR: found {len(anomalies)} anomalies in {kpi_name}")
    return anomalies


# =============================================================================
# MANN-KENDALL TREND DETECTION
# =============================================================================

def detect_trend_anomalies(
    series: pd.Series,
    kpi_name: str,
    significance_level: float = 0.05
) -> List[Anomaly]:
    """
    Detect significant trends using the Mann-Kendall test.

    How it works:
      The Mann-Kendall test checks whether a time series has a monotonic
      upward or downward trend. It counts concordant pairs (later value >
      earlier value) vs discordant pairs (later value < earlier value) and
      tests whether the imbalance is statistically significant.

    Unlike Z-score and IQR which flag individual point anomalies, this
    detects gradual drift — a metric slowly declining over weeks even if
    no single day looks unusual.

    Args:
        series: Time-indexed KPI values (needs 10+ points to be meaningful)
        kpi_name: Name of the KPI
        significance_level: p-value threshold for calling a trend significant

    Returns:
        A list with at most one Anomaly representing the overall trend.
        Date is set to the last point in the series (the trend culmination).

    Limitation:
        With only 13 months of weekly data (~52 points), results are
        borderline. Treat medium/low severity trend detections as signals
        to monitor rather than confirmed anomalies.
    """
    clean = series.dropna()

    if len(clean) < 10:
        logger.warning(f"Mann-Kendall: {kpi_name} has fewer than 10 points, skipping")
        return []

    values = clean.values
    n = len(values)

    # Calculate Mann-Kendall S statistic
    # S = sum of sign(x_j - x_i) for all j > i
    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            diff = values[j] - values[i]
            if diff > 0:
                s += 1
            elif diff < 0:
                s -= 1

    # Variance of S under null hypothesis (no trend)
    # Formula accounts for ties in the data
    var_s = (n * (n - 1) * (2 * n + 5)) / 18

    # Unique values and their counts for tie correction
    unique, counts = np.unique(values, return_counts=True)
    tie_correction = sum(c * (c - 1) * (2 * c + 5) for c in counts if c > 1)
    var_s -= tie_correction / 18

    if var_s <= 0:
        return []

    # Normalised test statistic Z_mk
    if s > 0:
        z_mk = (s - 1) / np.sqrt(var_s)
    elif s < 0:
        z_mk = (s + 1) / np.sqrt(var_s)
    else:
        return []  # No trend

    # Two-tailed p-value from standard normal distribution
    p_value = 2 * (1 - stats.norm.cdf(abs(z_mk)))

    if p_value > significance_level:
        logger.debug(f"Mann-Kendall: {kpi_name} trend not significant (p={p_value:.3f})")
        return []

    # Theil-Sen slope estimator — median of all pairwise slopes
    # More robust than linear regression slope
    slopes = []
    dates_numeric = np.arange(n)
    for i in range(n - 1):
        for j in range(i + 1, n):
            if dates_numeric[j] != dates_numeric[i]:
                slopes.append((values[j] - values[i]) / (dates_numeric[j] - dates_numeric[i]))

    slope = np.median(slopes) if slopes else 0

    # Direction of trend
    trend_direction = "upward" if s > 0 else "downward"

    # Expected value is the series mean, last value is the current state
    mean_val = float(clean.mean())
    last_val = float(clean.iloc[-1])
    deviation = last_val - mean_val
    deviation_pct = (deviation / mean_val) * 100 if mean_val != 0 else 0

    # Confidence inversely proportional to p-value
    confidence = min(0.99, 1 - p_value)

    anomaly = Anomaly(
        kpi_name=kpi_name,
        date=clean.index[-1],
        actual_value=last_val,
        expected_value=mean_val,
        deviation=float(deviation),
        deviation_pct=float(deviation_pct),
        method='mann_kendall',
        severity=severity_from_trend(p_value, slope),
        confidence=round(confidence, 3),
        stat_value=round(float(z_mk), 4),
        description=(
            f"{kpi_name} shows a statistically significant {trend_direction} trend "
            f"(p={p_value:.3f}, slope={slope:.4f} per period). "
            f"Current value {last_val:,.2f} vs series mean {mean_val:,.2f}."
        )
    )

    logger.debug(f"Mann-Kendall: {kpi_name} has significant {trend_direction} trend")
    return [anomaly]