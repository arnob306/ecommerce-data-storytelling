"""
Sales velocity: how fast each product sells, in units per week.

Quiet spells that were not caused by customer demand (a product being out of
stock, the COVID lockdown) are taken out of the denominator so they do not
make a product look slower than it really is.
"""

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

DEFAULT_WEEKS = 13
OUT_OF_STOCK_MARKER = 'out of stock'
LOCKDOWN_MARKER = 'lockdown'


@dataclass(frozen=True)
class CensoredWindow:
    """A date range when sales say little about demand."""
    start: pd.Timestamp
    end: pd.Timestamp
    product: Optional[str]  # None means it affects every product


def censored_windows(sales: pd.DataFrame) -> List[CensoredWindow]:
    """Find stock-out and lockdown periods from the Business Event labels."""
    labelled = sales[sales['event'].notna()]
    windows = []
    for name, group in labelled.groupby('event'):
        lowered = name.lower()
        if OUT_OF_STOCK_MARKER in lowered:
            product = name[: lowered.index(OUT_OF_STOCK_MARKER)].strip()
        elif LOCKDOWN_MARKER in lowered:
            product = None
        else:
            continue
        windows.append(
            CensoredWindow(group['date'].min(), group['date'].max(), product)
        )
    return windows


def _censored_days(days: pd.DatetimeIndex, windows, product: str) -> int:
    mask = pd.Series(False, index=days)
    for window in windows:
        if window.product is None or window.product == product:
            mask |= (days >= window.start) & (days <= window.end)
    return int(mask.sum())


def weekly_velocity(
    sales: pd.DataFrame,
    as_of,
    weeks: int = DEFAULT_WEEKS,
    windows: Optional[List[CensoredWindow]] = None,
) -> pd.DataFrame:
    """
    Units sold per week over the last ``weeks`` weeks up to ``as_of``.

    Refunds are ignored here: a return does not mean the customer did not
    want the product. Every product ever sold gets a row, even if zero.
    """
    as_of = pd.Timestamp(as_of).normalize()
    total_days = weeks * 7
    days = pd.date_range(as_of - pd.Timedelta(days=total_days - 1), as_of)
    windows = censored_windows(sales) if windows is None else windows

    recent = sales[
        (sales['date'] >= days[0]) & (sales['date'] <= as_of)
        & (sales['quantity'] > 0)
    ]
    units = recent.groupby('product')['quantity'].sum()
    counts = recent.groupby('product').size()

    rows = []
    for product in sorted(sales['product'].dropna().unique()):
        observed = (total_days - _censored_days(days, windows, product)) / 7
        product_units = int(units.get(product, 0))
        rows.append({
            'product': product,
            'units': product_units,
            'sales_count': int(counts.get(product, 0)),
            'weeks_observed': observed,
            'units_per_week': product_units / observed if observed > 0 else float('nan'),
        })
    return pd.DataFrame(rows).set_index('product')
