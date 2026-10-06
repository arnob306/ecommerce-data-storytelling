"""Guards that keep the real business data out of version control."""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PRIVATE_PATHS = [
    'data/private/raw/sales.xlsx',
    'data/private/inbox/Boutique_Sales.xlsx',
    'data/private/archive/2026-10-06_sales.xlsx',
    'data/private/output/weekly_report.html',
]


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['git', *args], cwd=REPO_ROOT, capture_output=True, text=True
    )


def test_private_data_paths_are_gitignored():
    for path in PRIVATE_PATHS:
        result = _git('check-ignore', '--quiet', path)
        assert result.returncode == 0, f'{path} is not gitignored'


def test_no_private_files_are_tracked():
    result = _git('ls-files', 'data/private')
    assert result.returncode == 0
    assert result.stdout.strip() == '', (
        f'Private files are tracked by git:\n{result.stdout}'
    )


def test_real_workbooks_are_never_tracked():
    result = _git('ls-files', '*Boutique_Sales*')
    assert result.stdout.strip() == ''


def test_env_file_is_gitignored():
    assert _git('check-ignore', '--quiet', '.env').returncode == 0
