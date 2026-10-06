"""Revenue, profit, margin and refund rate per product."""

from typing import Optional

import pandas as pd

COLUMNS = [
    'category', 'sales_count', 'units_sold', 'units_refunded', 'revenue',
    'revenue_costed', 'cost', 'profit', 'margin', 'refund_rate',
]


def _in_window(sales: pd.DataFrame, start, end) -> pd.DataFrame:
    mask = pd.Series(True, index=sales.index)
    if start is not None:
        mask &= sales['date'] >= pd.Timestamp(start)
    if end is not None:
        mask &= sales['date'] <= pd.Timestamp(end)
    return sales[mask]


def product_performance(
    sales: pd.DataFrame, start: Optional[object] = None, end: Optional[object] = None
) -> pd.DataFrame:
    """
    One row per product, best profit first.

    Revenue is net of refunds. Profit and margin only use sales that have a
    buy price, so a missing cost never inflates profit. Refunded items are
    assumed to go back on the shelf, so their cost is reversed too.
    """
    df = _in_window(sales, start, end)
    if df.empty:
        return pd.DataFrame(columns=COLUMNS).rename_axis('product')

    by_product = df.groupby('product')
    out = pd.DataFrame({
        'category': by_product['category'].first(),
        'sales_count': (df['quantity'] > 0).groupby(df['product']).sum(),
        'units_sold': df['quantity'].clip(lower=0).groupby(df['product']).sum(),
        'units_refunded': (-df['quantity']).clip(lower=0).groupby(df['product']).sum(),
        'revenue': by_product['line_total'].sum(),
    })

    costed = df[df['unit_cost'].notna()]
    cost_part = costed.assign(cost=costed['quantity'] * costed['unit_cost'])
    totals = cost_part.groupby('product').agg(
        revenue_costed=('line_total', 'sum'), cost=('cost', 'sum')
    )
    out = out.join(totals).fillna({'revenue_costed': 0.0, 'cost': 0.0})
    out['profit'] = out['revenue_costed'] - out['cost']
    has_costed_sales = out['revenue_costed'] > 0
    out['margin'] = (out['profit'] / out['revenue_costed']).where(has_costed_sales)
    out['refund_rate'] = (
        out['units_refunded'] / out['units_sold'].where(out['units_sold'] > 0)
    ).fillna(0.0)
    return out[COLUMNS].sort_values('profit', ascending=False)
