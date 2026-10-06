"""
Adapter for the boutique's Excel workbook.

Reads the sheets below and maps them into the standard schema in
``src.schema``. Personal details are removed here and never leave this module:
customer names become a keyed hash, and suburb and payment method are dropped.

Sheets:
    Sales           required, one row per sale line (refunds have IDs ending -R)
    Buy Prices      required, buy price per product per year
    Simple Summary  optional, used to reconcile totals
    Stock & Orders  optional, enables reorder advice
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from src.privacy import get_salt, hash_customer
from src.schema import REFUND_SUFFIX, STANDARD_COLUMNS, STOCK_COLUMNS

logger = logging.getLogger(__name__)

SALES_SHEET = 'Sales'
BUY_PRICES_SHEET = 'Buy Prices'
SUMMARY_SHEET = 'Simple Summary'
STOCK_SHEET = 'Stock & Orders'

SALES_COLUMN_MAP = {
    'Date': 'date',
    'Sale ID': 'sale_id',
    'Product': 'product',
    'Category': 'category',
    'Quantity': 'quantity',
    'Unit Price (AUD)': 'unit_price',
    'Sale Total (AUD)': 'line_total',
    'Sales Channel': 'channel',
    'Festival / Occasion': 'festival',
    'Business Event': 'event',
}
# Read only to build the customer hash, then discarded.
PERSONAL_COLUMNS = ('Customer', 'Suburb')

STOCK_COLUMN_MAP = {
    'Product': 'product',
    'Stock On Hand': 'stock_on_hand',
    'Count Date': 'count_date',
    'Weeks To Arrive': 'weeks_to_arrive',
    'Min Order Qty': 'min_order_qty',
    'On Order': 'on_order',
}
OPTIONAL_STOCK_COLUMNS = ('On Order',)

SUMMARY_LABELS = {
    'Total sales (AUD, after refunds)': 'total_sales',
    'Number of sales': 'number_of_sales',
    'Number of returns / refunds': 'number_of_refunds',
}


class SchemaError(ValueError):
    """Raised when the workbook does not look like the expected layout."""


@dataclass(frozen=True)
class WorkbookData:
    sales: pd.DataFrame
    buy_prices: pd.DataFrame
    stock: Optional[pd.DataFrame]
    summary: dict
    source_name: str


def _read_sheet(path: Path, sheet: str, **kwargs) -> pd.DataFrame:
    try:
        return pd.read_excel(path, sheet_name=sheet, **kwargs)
    except ValueError as exc:
        if 'Worksheet named' in str(exc):
            raise SchemaError(f"Sheet '{sheet}' is missing from {path.name}.")
        raise


def _require_columns(df: pd.DataFrame, required, sheet: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise SchemaError(
            f"Sheet '{sheet}' is missing column(s): {', '.join(missing)}. "
            'Check the headers have not been renamed.'
        )


def _numbers(series: pd.Series, column: str, sheet: str) -> pd.Series:
    """Convert to numbers, naming the sheet and column if any cell is not one."""
    converted = pd.to_numeric(series, errors='coerce')
    bad = int((converted.isna() & series.notna()).sum())
    if bad:
        raise SchemaError(
            f"{bad} cell(s) in '{column}' on sheet '{sheet}' are not numbers.")
    return converted


def _whole_numbers(series: pd.Series, column: str, sheet: str) -> pd.Series:
    converted = _numbers(series, column, sheet)
    if converted.isna().any():
        raise SchemaError(
            f"Some '{column}' cells on sheet '{sheet}' are empty.")
    return converted.astype(int)


def _clean_text(series: pd.Series) -> pd.Series:
    cleaned = series.astype('string').str.strip()
    return cleaned.where(cleaned.notna() & (cleaned != ''), None).astype(object)


def attach_unit_costs(sales: pd.DataFrame, buy_prices: pd.DataFrame) -> pd.DataFrame:
    """
    Add ``unit_cost`` and ``cost_is_estimated`` using the buy price for the
    sale's year. If the sale year has no price yet (a new year before the
    sheet is updated), use the product's latest known price and flag it.
    """
    out = sales.copy()
    years = out['date'].dt.year
    exact = buy_prices.set_index(['product', 'year'])['unit_cost']
    latest = (
        buy_prices.sort_values('year').groupby('product')['unit_cost'].last()
    )
    keys = pd.MultiIndex.from_arrays([out['product'], years])
    exact_cost = pd.Series(exact.reindex(keys).to_numpy(), index=out.index)
    fallback = out['product'].map(latest)
    out['unit_cost'] = exact_cost.fillna(fallback)
    out['cost_is_estimated'] = exact_cost.isna() & fallback.notna()
    return out


def _buy_price(value, product, year) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SchemaError(
            f"The {year} price for '{product}' on sheet '{BUY_PRICES_SHEET}' "
            'is not a number.') from None


def _read_buy_prices(path: Path) -> pd.DataFrame:
    raw = _read_sheet(path, BUY_PRICES_SHEET, header=None)
    header_rows = raw.index[raw[0].astype(str).str.strip() == 'Product']
    if len(header_rows) == 0:
        raise SchemaError(
            f"Sheet '{BUY_PRICES_SHEET}' needs a header row starting 'Product'."
        )
    header = header_rows[0]
    year_cols = {
        col: int(float(value))
        for col, value in raw.loc[header].items()
        if col > 1 and pd.notna(value) and str(value).split('.')[0].isdigit()
    }
    body = raw.loc[header + 1:]
    # The price table ends at the first blank row; the sheet has another
    # table (estimated profit) below it that must not be read as prices.
    blank_rows = body.index[body[0].isna()]
    if len(blank_rows):
        body = body.loc[: blank_rows[0] - 1]
    rows = [
        (str(row[0]).strip(), year, _buy_price(row[col], row[0], year))
        for _, row in body.iterrows()
        for col, year in year_cols.items()
        if pd.notna(row[col])
    ]
    return pd.DataFrame(rows, columns=['product', 'year', 'unit_cost'])


def _read_stock(path: Path) -> Optional[pd.DataFrame]:
    try:
        raw = _read_sheet(path, STOCK_SHEET)
    except SchemaError:
        return None
    required = [c for c in STOCK_COLUMN_MAP if c not in OPTIONAL_STOCK_COLUMNS]
    _require_columns(raw, required, STOCK_SHEET)
    for column in OPTIONAL_STOCK_COLUMNS:
        if column not in raw.columns:
            raw = raw.assign(**{column: 0})
    stock = raw[list(STOCK_COLUMN_MAP)].rename(columns=STOCK_COLUMN_MAP)
    # Rows still being filled in are skipped; no minimum order means 1.
    stock = stock.dropna(
        subset=['product', 'stock_on_hand', 'count_date', 'weeks_to_arrive']
    ).copy()
    if stock.empty:
        return None
    stock['product'] = stock['product'].astype(str).str.strip()
    stock['count_date'] = pd.to_datetime(stock['count_date'], errors='coerce')
    if stock['count_date'].isna().any():
        raise SchemaError(
            f"Some 'Count Date' cells on sheet '{STOCK_SHEET}' are not dates.")
    for column, label, default in (
        ('stock_on_hand', 'Stock On Hand', None),
        ('weeks_to_arrive', 'Weeks To Arrive', None),
        ('min_order_qty', 'Min Order Qty', 1),
        ('on_order', 'On Order', 0),
    ):
        numbers = _numbers(stock[column], label, STOCK_SHEET)
        if default is not None:
            numbers = numbers.fillna(default)
        stock[column] = numbers.astype(int)
    return stock[STOCK_COLUMNS].reset_index(drop=True)


def _read_summary(path: Path) -> dict:
    try:
        raw = _read_sheet(path, SUMMARY_SHEET, header=None)
    except SchemaError:
        return {}
    labels = dict(zip(raw[0], raw[1]))
    return {
        key: labels[label]
        for label, key in SUMMARY_LABELS.items()
        if label in labels and pd.notna(labels[label])
    }


def _build_sales(raw: pd.DataFrame, salt: str) -> pd.DataFrame:
    _require_columns(raw, [*SALES_COLUMN_MAP, *PERSONAL_COLUMNS], SALES_SHEET)
    if raw['Sale Total (AUD)'].isna().any():
        raise SchemaError(
            "Some 'Sale Total (AUD)' cells are empty. The formulas have no "
            'saved values - open the file in Excel, save it, and send it again.'
        )
    dates = pd.to_datetime(raw['Date'], errors='coerce')
    if dates.isna().any():
        bad = int(dates.isna().sum())
        raise SchemaError(f"{bad} row(s) have an unreadable 'Date'.")

    sales = raw[list(SALES_COLUMN_MAP)].rename(columns=SALES_COLUMN_MAP).copy()
    sales['date'] = dates
    sales['quantity'] = _whole_numbers(sales['quantity'], 'Quantity', SALES_SHEET)
    sales['unit_price'] = _numbers(
        sales['unit_price'], 'Unit Price (AUD)', SALES_SHEET).astype(float)
    sales['line_total'] = _numbers(
        sales['line_total'], 'Sale Total (AUD)', SALES_SHEET).astype(float)
    for col in ('sale_id', 'product', 'category', 'channel', 'festival', 'event'):
        sales[col] = _clean_text(sales[col])
    is_refund = sales['sale_id'].str.endswith(REFUND_SUFFIX).fillna(False)
    sales['refund_of'] = sales['sale_id'].where(is_refund).str[: -len(REFUND_SUFFIX)]
    sales['customer_id'] = [
        hash_customer(name, suburb, salt)
        for name, suburb in zip(raw['Customer'], raw['Suburb'])
    ]
    return sales


def load_workbook_data(path, salt: Optional[str] = None) -> WorkbookData:
    """Read the workbook at ``path`` into standard-schema DataFrames."""
    path = Path(path)
    salt = salt if salt is not None else get_salt()
    if not path.exists():
        raise FileNotFoundError(f'Workbook not found: {path.name}')

    raw_sales = _read_sheet(path, SALES_SHEET)
    sales = _build_sales(raw_sales, salt)
    buy_prices = _read_buy_prices(path)
    sales = attach_unit_costs(sales, buy_prices)[STANDARD_COLUMNS]
    logger.info('Loaded %d sales rows from %s', len(sales), path.name)

    return WorkbookData(
        sales=sales.reset_index(drop=True),
        buy_prices=buy_prices,
        stock=_read_stock(path),
        summary=_read_summary(path),
        source_name=path.name,
    )
