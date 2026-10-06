"""
Data models for anomaly detection results.

Defines the structure of an anomaly object that flows from
detector.py (Week 4) into root cause analysis (Week 5).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Anomaly:
    """
    Represents a single detected anomaly in a KPI time series.

    Produced by detector.py, consumed by root cause analysis in Week 5.
    Each anomaly captures not just that something is unusual, but how
    unusual, how confident we are, and which method detected it.
    """

    kpi_name: str
    date: datetime

    actual_value: float
    expected_value: float      
    deviation: float          
    deviation_pct: float       

    # Detection metadata
    method: str                # 'zscore', 'iqr', or 'mann_kendall'
    severity: str              # 'low', 'medium', 'high', 'critical'
    confidence: float          # 0.0 to 1.0 — how certain we are this is real

    # Method-specific detail
    # For zscore: the z-score value
    # For iqr: how far outside the fence it is
    # For mann_kendall: the trend slope
    stat_value: float

    # Human readable description seed for LLM narrative in future weeks
    description: str = ""

    def __post_init__(self):
        """Validate fields after initialisation."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be between 0 and 1, got {self.confidence}")

        valid_severities = {'low', 'medium', 'high', 'critical'}
        if self.severity not in valid_severities:
            raise ValueError(f"Severity must be one of {valid_severities}")

        valid_methods = {'zscore', 'iqr', 'mann_kendall', 'zscore_and_iqr', 'iqr_and_zscore'}
        if self.method not in valid_methods:
            raise ValueError(f"Method must be one of {valid_methods}")
        

        if not self.description:
            direction = "above" if self.deviation > 0 else "below"
            self.description = (
                f"{self.kpi_name} was {abs(self.deviation_pct):.1f}% {direction} "
                f"expected on {self.date.strftime('%Y-%m-%d')} "
                f"(actual: {self.actual_value:,.2f}, expected: {self.expected_value:,.2f}) "
                f"— detected by {self.method} with {self.confidence:.0%} confidence"
            )

    def to_dict(self) -> dict:
        """Serialise to dictionary for CSV saving and future API use."""
        return {
            'kpi_name': self.kpi_name,
            'date': self.date,
            'actual_value': self.actual_value,
            'expected_value': self.expected_value,
            'deviation': self.deviation,
            'deviation_pct': self.deviation_pct,
            'method': self.method,
            'severity': self.severity,
            'confidence': self.confidence,
            'stat_value': self.stat_value,
            'description': self.description
        }


def severity_from_zscore(z: float) -> str:
    """
    Map a Z-score magnitude to a severity label.

    Thresholds chosen to be meaningful for business metrics:
    - Low: slightly unusual, worth monitoring
    - Medium: clearly abnormal, investigate soon
    - High: significantly abnormal, investigate today
    - Critical: extreme deviation, act immediately
    """
    z = abs(z)
    if z >= 4.0:
        return 'critical'
    elif z >= 3.0:
        return 'high'
    elif z >= 2.5:
        return 'medium'
    else:
        return 'low'


def severity_from_iqr(multiplier: float) -> str:
    """
    Map an IQR fence multiplier to a severity label.

    How far outside the IQR fence the value is:
    - 1.5x fence: standard outlier threshold (low)
    - 2.0x fence: moderate outlier (medium)
    - 2.5x fence: strong outlier (high)
    - 3.0x fence: extreme outlier (critical)
    """
    if multiplier >= 3.0:
        return 'critical'
    elif multiplier >= 2.5:
        return 'high'
    elif multiplier >= 2.0:
        return 'medium'
    else:
        return 'low'


def severity_from_trend(p_value: float, slope: float) -> str:
    """
    Map Mann-Kendall p-value and slope to severity.

    p-value tells us how statistically significant the trend is.
    Slope magnitude tells us how fast the metric is changing.
    """
    if p_value <= 0.01:
        return 'high' if abs(slope) > 0.05 else 'medium'
    elif p_value <= 0.05:
        return 'medium' if abs(slope) > 0.02 else 'low'
    else:
        return 'low'