"""Upcoming festival dates, loaded from config/festivals.yaml."""

from dataclasses import dataclass
from pathlib import Path
from typing import List

import pandas as pd
import yaml

DEFAULT_CALENDAR_PATH = Path('config/festivals.yaml')


@dataclass(frozen=True)
class FestivalWindow:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp


def load_calendar(path=DEFAULT_CALENDAR_PATH) -> List[FestivalWindow]:
    """Read festival windows, rejecting any whose end is before its start."""
    with open(path, encoding='utf-8') as handle:
        entries = (yaml.safe_load(handle) or {}).get('festivals', [])
    windows = []
    for entry in entries:
        window = FestivalWindow(
            str(entry['name']),
            pd.Timestamp(entry['start']),
            pd.Timestamp(entry['end']),
        )
        if window.start > window.end:
            raise ValueError(f'Festival {window.name} ends before it starts.')
        windows.append(window)
    return windows


def upcoming(calendar, start, end) -> List[FestivalWindow]:
    """Festival windows that overlap the period from ``start`` to ``end``."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    return [w for w in calendar if w.end >= start and w.start <= end]
