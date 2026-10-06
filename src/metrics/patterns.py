"""Day-of-week and festival patterns learned from the sales history."""

import pandas as pd

from src.metrics.velocity import censored_windows

WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
            'Saturday', 'Sunday']
CLUSTER_GAP_DAYS = 14
MIN_ROWS_PER_WINDOW = 3
MAX_WINDOW_DAYS = 45
MIN_WINDOWS_FOR_UPLIFT = 2

WINDOW_COLUMNS = ['festival', 'start', 'end', 'rows']
UPLIFT_COLUMNS = ['festival', 'category', 'uplift', 'windows']


def day_of_week_pattern(sales: pd.DataFrame, as_of, weeks: int = 52) -> pd.DataFrame:
    """Share of recent sales that happen on each day of the week."""
    as_of = pd.Timestamp(as_of).normalize()
    start = as_of - pd.Timedelta(weeks=weeks)
    recent = sales[
        (sales['date'] > start) & (sales['date'] <= as_of) & (sales['quantity'] > 0)
    ]
    counts = recent['date'].dt.day_name().value_counts().reindex(WEEKDAYS, fill_value=0)
    total = counts.sum()
    share = counts / total if total else counts.astype(float)
    result = pd.DataFrame({'sales_count': counts, 'share': share})
    return result.rename_axis('weekday')


def festival_windows(sales: pd.DataFrame) -> pd.DataFrame:
    """
    Find each festival's busy windows from the Festival / Occasion labels.

    Labels that appear close together form one window. Bursts spread over
    more than ~6 weeks (like family events through the year) are not
    treated as a single festival.
    """
    labelled = sales[sales['festival'].notna()]
    found = []
    for name, group in labelled.groupby('festival'):
        dates = group['date'].sort_values().reset_index(drop=True)
        cluster = (dates.diff().dt.days > CLUSTER_GAP_DAYS).cumsum()
        for _, burst in dates.groupby(cluster):
            span = (burst.max() - burst.min()).days + 1
            if len(burst) < MIN_ROWS_PER_WINDOW or span > MAX_WINDOW_DAYS:
                continue
            found.append({
                'festival': name, 'start': burst.min(), 'end': burst.max(),
                'rows': len(burst),
            })
    return pd.DataFrame(found, columns=WINDOW_COLUMNS)


def _daily_units(sales: pd.DataFrame) -> pd.DataFrame:
    positive = sales[sales['quantity'] > 0]
    full_range = pd.date_range(
        sales['date'].min().normalize(), sales['date'].max().normalize()
    )
    daily = positive.groupby(
        [positive['date'].dt.normalize(), 'category']
    )['quantity'].sum().unstack(fill_value=0)
    return daily.reindex(full_range, fill_value=0)


def _baseline_mask(index: pd.DatetimeIndex, windows: pd.DataFrame, sales) -> pd.Series:
    """True for ordinary days: not in a festival window or a lockdown."""
    ordinary = pd.Series(True, index=index)
    for _, w in windows.iterrows():
        ordinary[(index >= w['start']) & (index <= w['end'])] = False
    for cw in censored_windows(sales):
        if cw.product is None:
            ordinary[(index >= cw.start) & (index <= cw.end)] = False
    return ordinary


def festival_uplift(sales: pd.DataFrame) -> pd.DataFrame:
    """
    How much faster each category sells during each festival.

    Uplift is the festival window's units per day divided by the ordinary
    units per day in the same year, taking the median across years. A
    festival needs at least two windows in the history to get a figure.
    """
    windows = festival_windows(sales)
    if windows.empty or not (sales['quantity'] > 0).any():
        return pd.DataFrame(columns=UPLIFT_COLUMNS)

    daily = _daily_units(sales)
    ordinary = _baseline_mask(daily.index, windows, sales)
    ratios = []
    for _, w in windows.iterrows():
        in_year = ordinary & (daily.index.year == w['start'].year)
        for category in daily.columns:
            base = daily.loc[in_year, category].mean()
            if not base or pd.isna(base):
                continue
            rate = daily.loc[w['start']:w['end'], category].mean()
            ratios.append((w['festival'], category, rate / base))

    table = pd.DataFrame(ratios, columns=['festival', 'category', 'ratio'])
    grouped = table.groupby(['festival', 'category'])['ratio'].agg(['median', 'size'])
    grouped = grouped[grouped['size'] >= MIN_WINDOWS_FOR_UPLIFT].reset_index()
    return grouped.rename(columns={'median': 'uplift', 'size': 'windows'})[UPLIFT_COLUMNS]
