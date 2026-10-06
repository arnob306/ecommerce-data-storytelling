"""
Reorder suggestions.

For each product on the stock sheet, estimate demand over "shipment lead time
plus one week" (the time until the next chance to order), scale it for any
festival in that period, add a small safety buffer, and subtract the stock
she should still have. Items with few recent sales are marked low confidence
instead of pretending to be precise.
"""

import math
from typing import Optional

import pandas as pd

from src.metrics.calendar import upcoming
from src.metrics.velocity import DEFAULT_WEEKS, weekly_velocity

REVIEW_DAYS = 7
SAFETY_Z = 1.0
LOW_CONFIDENCE_BELOW = 6
GOOD_CONFIDENCE_FROM = 15

COLUMNS = [
    'product', 'stock_now', 'on_order', 'units_per_week', 'weeks_of_cover', 'lead_weeks',
    'expected_demand', 'safety_stock', 'target', 'order_qty', 'confidence',
    'note',
]


def _confidence(sales_count: int) -> str:
    if sales_count < LOW_CONFIDENCE_BELOW:
        return 'low'
    return 'good' if sales_count >= GOOD_CONFIDENCE_FROM else 'medium'


def _stock_now(sales, product, on_hand, count_date, as_of) -> int:
    """Stock on the count date, less net sales since (refunds put items back)."""
    since = sales[
        (sales['product'] == product)
        & (sales['date'] > count_date) & (sales['date'] <= as_of)
    ]
    return max(0, int(on_hand - since['quantity'].sum()))


def _festival_factor(calendar, uplift, category, as_of, horizon_days):
    """Demand multiplier and notes for festivals inside the order horizon."""
    start = as_of + pd.Timedelta(days=1)
    end = as_of + pd.Timedelta(days=horizon_days)
    factor, notes = 1.0, []
    for window in upcoming(calendar, start, end):
        overlap = (min(window.end, end) - max(window.start, start)).days + 1
        match = uplift[
            (uplift['festival'] == window.name) & (uplift['category'] == category)
        ] if uplift is not None and not uplift.empty else None
        if match is None or match.empty:
            continue
        boost = float(match['uplift'].iloc[0])
        factor += overlap / horizon_days * (boost - 1.0)
        notes.append(f'{window.name} coming up (about {boost:.1f}x usual sales)')
    return factor, notes


def _suggest(row, sales, velocity, categories, calendar, uplift, as_of) -> dict:
    product = row.product
    vel = velocity.loc[product] if product in velocity.index else None
    per_week = float(vel['units_per_week']) if vel is not None else 0.0
    sales_count = int(vel['sales_count']) if vel is not None else 0
    stock_now = _stock_now(sales, product, row.stock_on_hand, row.count_date, as_of)
    on_order = int(getattr(row, 'on_order', 0))
    base = {
        'product': product, 'stock_now': stock_now, 'on_order': on_order,
        'units_per_week': per_week,
        'lead_weeks': int(row.weeks_to_arrive),
        'confidence': _confidence(sales_count),
    }
    if not per_week > 0:
        return {**base, 'weeks_of_cover': math.inf, 'expected_demand': 0.0,
                'safety_stock': 0, 'target': 0.0, 'order_qty': 0,
                'note': 'no recent sales'}

    horizon = int(row.weeks_to_arrive) * 7 + REVIEW_DAYS
    factor, notes = _festival_factor(
        calendar, uplift, categories.get(product), as_of, horizon)
    expected = per_week / 7 * horizon * factor
    safety = math.ceil(SAFETY_Z * math.sqrt(expected))
    target = expected + safety
    need = max(0, math.ceil(target - stock_now - on_order - 1e-9))
    order_qty = max(need, int(row.min_order_qty)) if need > 0 else 0
    return {**base, 'weeks_of_cover': stock_now / per_week,
            'expected_demand': expected, 'safety_stock': safety,
            'target': target, 'order_qty': order_qty,
            'note': '; '.join(notes) if notes else ''}


def reorder_suggestions(
    sales: pd.DataFrame,
    stock: Optional[pd.DataFrame],
    as_of,
    calendar=(),
    uplift: Optional[pd.DataFrame] = None,
    weeks: int = DEFAULT_WEEKS,
) -> pd.DataFrame:
    """Return one row per stocked product, biggest orders first."""
    if stock is None or stock.empty:
        return pd.DataFrame(columns=COLUMNS)
    as_of = pd.Timestamp(as_of).normalize()
    velocity = weekly_velocity(sales, as_of, weeks)
    categories = sales.drop_duplicates('product').set_index('product')['category']
    rows = [
        _suggest(row, sales, velocity, categories, calendar, uplift, as_of)
        for row in stock.itertuples()
    ]
    result = pd.DataFrame(rows, columns=COLUMNS)
    return result.sort_values(
        ['order_qty', 'product'], ascending=[False, True]
    ).reset_index(drop=True)
