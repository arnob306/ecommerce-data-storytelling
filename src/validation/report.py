"""Result types for the import check."""

from dataclasses import dataclass
from typing import Tuple

import pandas as pd

SEVERITIES = ('critical', 'warning', 'info')
_MARKERS = {'critical': '[STOP]', 'warning': '[CHECK]', 'info': '[note]'}


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str
    count: int = 0


@dataclass(frozen=True)
class ImportReport:
    rows: int
    first_date: pd.Timestamp
    last_date: pd.Timestamp
    issues: Tuple[Issue, ...]

    @property
    def ok(self) -> bool:
        """True when nothing critical was found, so reports can be trusted."""
        return self.count('critical') == 0

    def count(self, severity: str) -> int:
        """Number of issues with the given severity."""
        return sum(1 for issue in self.issues if issue.severity == severity)

    def to_text(self) -> str:
        """Plain-text summary, safe to print or email."""
        status = 'OK' if self.ok else 'PROBLEMS FOUND - report not trusted'
        lines = [
            f'Import check: {status}',
            f'{self.rows:,} rows from {self.first_date:%d %b %Y} '
            f'to {self.last_date:%d %b %Y}',
        ]
        ordered = sorted(self.issues, key=lambda i: SEVERITIES.index(i.severity))
        lines += [f'{_MARKERS[i.severity]} {i.message}' for i in ordered]
        return '\n'.join(lines)
