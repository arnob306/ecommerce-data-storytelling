"""Shared fixtures. All data here is synthetic; tests never touch data/private/."""

from pathlib import Path

import pytest

from src.synthetic.generator import generate_workbook

# Throwaway workbooks only need a few months of data, which keeps tests fast.
SHORT_START = '2026-01-01'


@pytest.fixture(scope='session')
def workbook_path(tmp_path_factory) -> Path:
    """A clean synthetic workbook shared by read-only tests."""
    path = tmp_path_factory.mktemp('synthetic') / 'boutique.xlsx'
    return generate_workbook(path, seed=7)


@pytest.fixture
def make_workbook(tmp_path):
    """Factory for workbooks with specific problems injected."""
    def _make(name: str = 'boutique.xlsx', **kwargs) -> Path:
        kwargs.setdefault('start', SHORT_START)
        return generate_workbook(tmp_path / name, **kwargs)
    return _make
