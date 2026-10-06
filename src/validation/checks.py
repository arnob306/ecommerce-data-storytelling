"""
Checks run after every import.

Each check returns an Issue (or None when everything is fine). Critical issues
mean the numbers cannot be trusted; warnings mean some figures are weaker than
usual; info is just worth knowing.
"""

import logging
from typing import Callable, List, Optional

import pandas as pd

from src.adapters.boutique_xlsx import WorkbookData
from src.validation.report import ImportReport, Issue

logger = logging.getLogger(__name__)

STALE_AFTER_DAYS = 10
STOCK_STALE_AFTER_DAYS = 21
RECENT_PRODUCT_DAYS = 365
LINE_TOTAL_TOLERANCE = 0.01
RECONCILE_TOLERANCE = 0.5
EXAMPLE_LIMIT = 3
REQUIRED_VALUES = (
    'date', 'sale_id', 'product', 'category', 'quantity', 'unit_price',
)


def _examples(values) -> str:
    shown = [str(v) for v in list(values)[:EXAMPLE_LIMIT]]
    return ', '.join(shown)


def _missing_values(data: WorkbookData, as_of) -> Optional[Issue]:
    missing = data.sales[list(REQUIRED_VALUES)].isna().any(axis=1).sum()
    if not missing:
        return None
    return Issue(
        'critical', 'missing_values',
        f'{missing} row(s) are missing a date, ID, product, category, '
        'quantity or price.', int(missing),
    )


def _duplicate_ids(data: WorkbookData, as_of) -> Optional[Issue]:
    dupes = data.sales['sale_id'][data.sales['sale_id'].duplicated(keep=False)]
    if dupes.empty:
        return None
    ids = dupes.unique()
    return Issue(
        'critical', 'duplicate_sale_id',
        f'{len(ids)} Sale ID(s) appear more than once (e.g. {_examples(ids)}). '
        'Sales may be counted twice.', len(ids),
    )


def _line_total_mismatch(data: WorkbookData, as_of) -> Optional[Issue]:
    sales = data.sales
    gap = (sales['line_total'] - sales['quantity'] * sales['unit_price']).abs()
    bad = sales[gap > LINE_TOTAL_TOLERANCE]
    if bad.empty:
        return None
    return Issue(
        'critical', 'line_total_mismatch',
        f"{len(bad)} sale(s) have a total that is not quantity x price "
        f"(e.g. {_examples(bad['sale_id'])}).", len(bad),
    )


def _non_positive_price(data: WorkbookData, as_of) -> Optional[Issue]:
    bad = data.sales[data.sales['unit_price'] <= 0]
    if bad.empty:
        return None
    return Issue(
        'critical', 'non_positive_price',
        f"{len(bad)} sale(s) have a price of zero or less "
        f"(e.g. {_examples(bad['sale_id'])}).", len(bad),
    )


def _refund_sign_mismatch(data: WorkbookData, as_of) -> Optional[Issue]:
    sales = data.sales
    marked = sales['refund_of'].notna()
    bad = sales[marked != (sales['quantity'] < 0)]
    if bad.empty:
        return None
    return Issue(
        'critical', 'refund_sign_mismatch',
        f"{len(bad)} row(s) have a negative quantity but no '-R' Sale ID, "
        f"or the reverse (e.g. {_examples(bad['sale_id'])}).", len(bad),
    )


def _orphan_refunds(data: WorkbookData, as_of) -> Optional[Issue]:
    sales = data.sales
    refunds = sales[sales['refund_of'].notna()]
    orphans = refunds[~refunds['refund_of'].isin(set(sales['sale_id']))]
    if orphans.empty:
        return None
    return Issue(
        'warning', 'orphan_refund',
        f"{len(orphans)} refund(s) point to a sale that is not in the sheet "
        f"(e.g. {_examples(orphans['sale_id'])}).", len(orphans),
    )


def _refund_exceeds_sale(data: WorkbookData, as_of) -> Optional[Issue]:
    sales = data.sales
    refunds = sales[sales['refund_of'].notna()]
    refunded = refunds.groupby('refund_of')['quantity'].sum().abs()
    sold = sales.drop_duplicates('sale_id').set_index('sale_id')['quantity']
    too_many = refunded[refunded > sold.reindex(refunded.index)]
    if too_many.empty:
        return None
    return Issue(
        'warning', 'refund_exceeds_sale',
        f'{len(too_many)} sale(s) were refunded for more items than were '
        f'sold (e.g. {_examples(too_many.index)}).', len(too_many),
    )


def _refunds(data: WorkbookData, as_of) -> Optional[Issue]:
    refunds = data.sales[data.sales['quantity'] < 0]
    value = -refunds['line_total'].sum()
    return Issue(
        'info', 'refunds',
        f'{len(refunds)} refund row(s) worth ${value:,.2f}, '
        'subtracted from sales.', len(refunds),
    )


def _unknown_products(data: WorkbookData, as_of) -> Optional[Issue]:
    unknown = data.sales.loc[data.sales['unit_cost'].isna(), 'product']
    if unknown.empty:
        return None
    names = sorted(unknown.dropna().unique())
    return Issue(
        'warning', 'unknown_product',
        f"{len(unknown)} sale(s) are for product(s) with no buy price: "
        f"{', '.join(names)}. They are left out of profit figures.",
        len(unknown),
    )


def _estimated_costs(data: WorkbookData, as_of) -> Optional[Issue]:
    count = int(data.sales['cost_is_estimated'].sum())
    if not count:
        return None
    return Issue(
        'warning', 'estimated_costs',
        f"{count} sale(s) use the latest known buy price because this year's "
        "price is not in the 'Buy Prices' sheet yet.", count,
    )


def _stale_data(data: WorkbookData, as_of) -> Optional[Issue]:
    age = (as_of - data.sales['date'].max()).days
    if age <= STALE_AFTER_DAYS:
        return None
    return Issue(
        'warning', 'stale_data',
        f'The newest sale is {age} days old. This week may be missing.', age,
    )


def _future_dates(data: WorkbookData, as_of) -> Optional[Issue]:
    future = data.sales[data.sales['date'] > as_of]
    if future.empty:
        return None
    return Issue(
        'warning', 'future_dates',
        f'{len(future)} sale(s) are dated after today.', len(future),
    )


def _reconciliation(data: WorkbookData, as_of) -> Optional[Issue]:
    summary = data.summary
    quantity = data.sales['quantity']
    computed = {
        'total_sales': data.sales['line_total'].sum(),
        'number_of_sales': (quantity > 0).sum(),
        'number_of_refunds': (quantity < 0).sum(),
    }
    off = [
        name for name, value in computed.items()
        if name in summary and abs(summary[name] - value) > RECONCILE_TOLERANCE
    ]
    if not off:
        return None
    return Issue(
        'warning', 'reconciliation',
        "The 'Simple Summary' sheet does not match the Sales sheet for: "
        f"{', '.join(off)}. The summary may be out of date.", len(off),
    )


def _no_stock_sheet(data: WorkbookData, as_of) -> Optional[Issue]:
    if data.stock is not None:
        return None
    return Issue(
        'info', 'no_stock_sheet',
        "No 'Stock & Orders' sheet, so reorder advice is switched off.",
    )


def _stock_stale(data: WorkbookData, as_of) -> Optional[Issue]:
    if data.stock is None:
        return None
    age = (as_of - data.stock['count_date'].max()).days
    if age <= STOCK_STALE_AFTER_DAYS:
        return None
    return Issue(
        'warning', 'stock_stale',
        f'Stock was last counted {age} days ago. Reorder advice may be off.',
        age,
    )


def _stock_missing_product(data: WorkbookData, as_of) -> Optional[Issue]:
    if data.stock is None:
        return None
    sales = data.sales
    recent = sales[sales['date'] > as_of - pd.Timedelta(days=RECENT_PRODUCT_DAYS)]
    missing = sorted(set(recent['product'].dropna()) - set(data.stock['product']))
    if not missing:
        return None
    return Issue(
        'warning', 'stock_missing_product',
        f"Sold in the last year but not in 'Stock & Orders': "
        f"{', '.join(missing)}.", len(missing),
    )


CHECKS: List[Callable] = [
    _missing_values, _duplicate_ids, _line_total_mismatch, _non_positive_price,
    _refund_sign_mismatch, _orphan_refunds, _refund_exceeds_sale, _refunds,
    _unknown_products, _estimated_costs, _stale_data, _future_dates,
    _reconciliation, _no_stock_sheet, _stock_stale, _stock_missing_product,
]


def validate_import(data: WorkbookData, as_of=None) -> ImportReport:
    """Run every check and return the report. ``as_of`` defaults to today."""
    as_of = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.today().normalize()
    issues = tuple(
        issue for check in CHECKS
        if (issue := check(data, as_of)) is not None
    )
    logger.info('Import check found %d issue(s)', len(issues))
    return ImportReport(
        rows=len(data.sales),
        first_date=data.sales['date'].min(),
        last_date=data.sales['date'].max(),
        issues=issues,
    )
