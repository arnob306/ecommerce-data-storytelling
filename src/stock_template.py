"""
Blank 'Stock & Orders' sheet for the workbook.

Reorder advice needs to know what is on the shelf and how long a shipment
takes. This writes a small workbook with one row per product sold in the last
year so she only has to type numbers, then copy the sheet into her workbook
(Excel: right-click the tab, Move or Copy). It is a separate file on purpose:
re-saving her workbook with another tool would wipe the saved results of her
formulas.
"""

from pathlib import Path

import pandas as pd
from openpyxl import Workbook

SHEET_NAME = 'Stock & Orders'
HEADERS = ['Product', 'Stock On Hand', 'Count Date', 'Weeks To Arrive',
           'Min Order Qty', 'On Order']
DEFAULT_MIN_ORDER_QTY = 1
DEFAULT_ON_ORDER = 0
LOOKBACK_DAYS = 365
COLUMN_WIDTHS = {'A': 28, 'B': 16, 'C': 14, 'D': 18, 'E': 16, 'F': 12}

INSTRUCTIONS = [
    'How to fill in the Stock & Orders sheet',
    '',
    'Stock On Hand: how many of each item you have right now.',
    'Count Date: the day you counted (a date like 2026-10-05).',
    'Weeks To Arrive: how many weeks a shipment takes from ordering to arriving.',
    'Min Order Qty: the smallest number you can order at once (1 if no minimum).',
    'On Order: items you have already ordered that have not arrived yet (0 if none).',
    '',
    'Update Stock On Hand and Count Date whenever you count the shelves.',
    'Rows left blank are skipped, so you can fill them in a few at a time.',
    '',
    'Then copy the "Stock & Orders" sheet into your sales workbook:',
    'right-click its tab, choose Move or Copy, pick your workbook, tick',
    '"Create a copy", and save.',
]


def _recent_products(sales: pd.DataFrame, as_of: pd.Timestamp) -> list:
    start = as_of - pd.Timedelta(days=LOOKBACK_DAYS)
    recent = sales[
        (sales['date'] > start) & (sales['date'] <= as_of) & (sales['quantity'] > 0)
    ]
    return sorted(recent['product'].dropna().unique())


def write_stock_template(sales: pd.DataFrame, path, as_of) -> Path:
    """Write the template to ``path`` and return the path."""
    as_of = pd.Timestamp(as_of).normalize()
    wb = Workbook()
    sheet = wb.active
    sheet.title = SHEET_NAME
    sheet.append(HEADERS)
    for product in _recent_products(sales, as_of):
        sheet.append([product, None, None, None, DEFAULT_MIN_ORDER_QTY,
                      DEFAULT_ON_ORDER])
    for column, width in COLUMN_WIDTHS.items():
        sheet.column_dimensions[column].width = width

    help_sheet = wb.create_sheet('How to fill in')
    for line in INSTRUCTIONS:
        help_sheet.append([line])
    help_sheet.column_dimensions['A'].width = 80

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
