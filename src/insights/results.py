"""
Data models for root cause analysis results.

Defines the structure of a root cause result that flows from
analyser.py (Phase 5) into narratives and dashboard (future phases).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class SegmentContribution:
    """
    Represents how much a single segment value contributed to an anomaly.

    For example: Country='Germany' contributed £12,400 of the £18,000
    total deviation, which is 68.9% of the anomaly.

    This is the atomic unit of root cause analysis - one segment value,
    one dimension, one contribution score.
    """
    dimension: str        # e.g. 'Country', 'StockCode', 'HourOfDay'
    segment_value: str    # e.g. 'Germany', '85123A', '14'
    actual_value: float   # actual metric value for this segment in anomaly period
    expected_value: float # baseline expected value for this segment
    deviation: float      # actual - expected
    contribution_pct: float  # this segment's share of the total anomaly deviation


@dataclass
class RootCauseResult:
    """
    Root cause analysis result for a single anomaly.

    Produced by analyser.py, consumed by narrative generation and
    dashboard in future phases.

    Contains the original anomaly details plus ranked segment contributions
    across all analysed dimensions.
    """
    # Which anomaly this explains
    kpi_name: str
    date: datetime
    anomaly_severity: str
    anomaly_confidence: float
    total_deviation: float
    total_deviation_pct: float

    # Top contributing segments ranked by absolute contribution
    # Each entry is a SegmentContribution for one dimension
    top_segments: List[SegmentContribution] = field(default_factory=list)

    # Which dimensions were analysed
    dimensions_analysed: List[str] = field(default_factory=list)

    # Whether root cause was successfully identified or flagged for manual review
    # Ratio KPIs (repeat_customer_rate etc) cannot be sliced directly
    status: str = 'analysed'  # 'analysed', 'manual_review_required', 'insufficient_data'

    # Plain English summary - seed for LLM narrative in future phases
    summary: str = ''

    def __post_init__(self):
        if self.status not in {'analysed', 'manual_review_required', 'insufficient_data'}:
            raise ValueError(f'Invalid status: {self.status}')

        # Auto-generate summary if not provided
        if not self.summary and self.status == 'analysed' and self.top_segments:
            top = self.top_segments[0]
            direction = 'above' if self.total_deviation > 0 else 'below'
            self.summary = (
                f'{self.kpi_name} was {abs(self.total_deviation_pct):.1f}% {direction} '
                f'expected on {self.date.strftime("%Y-%m-%d")}. '
                f'Primary driver: {top.dimension}={top.segment_value} '
                f'accounted for {top.contribution_pct:.1f}% of the deviation.'
            )
        elif self.status == 'manual_review_required':
            self.summary = (
                f'{self.kpi_name} anomaly on {self.date.strftime("%Y-%m-%d")} '
                f'requires manual investigation - ratio KPI cannot be directly segmented.'
            )

    def to_dict(self) -> dict:
        """Serialise to flat dictionary for CSV output."""
        base = {
            'kpi_name': self.kpi_name,
            'date': self.date,
            'anomaly_severity': self.anomaly_severity,
            'anomaly_confidence': self.anomaly_confidence,
            'total_deviation': self.total_deviation,
            'total_deviation_pct': self.total_deviation_pct,
            'status': self.status,
            'summary': self.summary,
            'dimensions_analysed': ', '.join(self.dimensions_analysed)
        }
        # Flatten top 3 segments into columns for easy CSV reading
        for i, seg in enumerate(self.top_segments[:3], 1):
            base[f'driver_{i}_dimension'] = seg.dimension
            base[f'driver_{i}_segment'] = seg.segment_value
            base[f'driver_{i}_contribution_pct'] = seg.contribution_pct
            base[f'driver_{i}_deviation'] = seg.deviation

        return base