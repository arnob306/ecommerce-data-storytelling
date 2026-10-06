from dataclasses import replace

import pandas as pd
import pytest

from src.adapters.boutique_xlsx import load_workbook_data
from src.validation.checks import validate_import

SALT = 'unit-test-salt-0123456789'


@pytest.fixture(scope='module')
def clean(workbook_path):
    return load_workbook_data(workbook_path, salt=SALT)


@pytest.fixture(scope='module')
def as_of(clean):
    return clean.sales['date'].max() + pd.Timedelta(days=1)


def _codes(report):
    return {issue.code for issue in report.issues}


def _issue(report, code):
    return next(i for i in report.issues if i.code == code)


def _with_sales(data, sales):
    return replace(data, sales=sales)


def test_clean_data_has_no_critical_issues_or_warnings(clean, as_of):
    report = validate_import(clean, as_of=as_of)
    assert report.ok
    assert report.count('critical') == 0
    assert report.count('warning') == 0


def test_report_describes_the_import(clean, as_of):
    report = validate_import(clean, as_of=as_of)
    assert report.rows == len(clean.sales)
    assert report.first_date == clean.sales['date'].min()
    assert report.last_date == clean.sales['date'].max()


def test_refunds_are_reported_as_information(clean, as_of):
    report = validate_import(clean, as_of=as_of)
    refunds = _issue(report, 'refunds')
    assert refunds.severity == 'info'
    assert refunds.count == (clean.sales['quantity'] < 0).sum()


def test_duplicate_sale_ids_are_critical(make_workbook, as_of):
    data = load_workbook_data(
        make_workbook(problems={'duplicate_id'}), salt=SALT
    )
    report = validate_import(data, as_of=data.sales['date'].max())
    assert not report.ok
    assert _issue(report, 'duplicate_sale_id').severity == 'critical'


def test_orphan_refunds_are_warned(make_workbook):
    data = load_workbook_data(
        make_workbook(problems={'orphan_refund'}), salt=SALT
    )
    report = validate_import(data, as_of=data.sales['date'].max())
    issue = _issue(report, 'orphan_refund')
    assert issue.severity == 'warning'
    assert issue.count == 1


def test_unknown_products_are_named_and_warned(make_workbook):
    data = load_workbook_data(
        make_workbook(problems={'unknown_product'}), salt=SALT
    )
    report = validate_import(data, as_of=data.sales['date'].max())
    issue = _issue(report, 'unknown_product')
    assert issue.severity == 'warning'
    assert 'Mystery Item' in issue.message


def test_total_that_is_not_quantity_times_price_is_critical(make_workbook):
    data = load_workbook_data(make_workbook(problems={'bad_total'}), salt=SALT)
    report = validate_import(data, as_of=data.sales['date'].max())
    assert _issue(report, 'line_total_mismatch').severity == 'critical'
    assert not report.ok


def test_stale_data_is_warned(clean):
    late = clean.sales['date'].max() + pd.Timedelta(days=30)
    report = validate_import(clean, as_of=late)
    assert _issue(report, 'stale_data').severity == 'warning'


def test_fresh_data_is_not_stale(clean, as_of):
    assert 'stale_data' not in _codes(validate_import(clean, as_of=as_of))


def test_dates_after_today_are_flagged(clean):
    early = clean.sales['date'].max() - pd.Timedelta(days=10)
    report = validate_import(clean, as_of=early)
    assert 'future_dates' in _codes(report)


def test_refund_larger_than_the_sale_is_warned(clean, as_of):
    sales = clean.sales.copy()
    idx = sales.index[sales['refund_of'].notna()][0]
    sales.loc[idx, 'quantity'] = -999
    report = validate_import(_with_sales(clean, sales), as_of=as_of)
    assert 'refund_exceeds_sale' in _codes(report)


def test_zero_or_negative_prices_are_critical(clean, as_of):
    sales = clean.sales.copy()
    sales.loc[sales.index[0], 'unit_price'] = 0.0
    report = validate_import(_with_sales(clean, sales), as_of=as_of)
    assert _issue(report, 'non_positive_price').severity == 'critical'


def test_negative_quantity_without_refund_id_is_critical(clean, as_of):
    sales = clean.sales.copy()
    first_sale = sales.index[sales['refund_of'].isna()][0]
    sales.loc[first_sale, 'quantity'] = -1
    report = validate_import(_with_sales(clean, sales), as_of=as_of)
    assert _issue(report, 'refund_sign_mismatch').severity == 'critical'


def test_missing_required_values_are_critical(clean, as_of):
    sales = clean.sales.copy()
    sales.loc[sales.index[3], 'product'] = None
    report = validate_import(_with_sales(clean, sales), as_of=as_of)
    assert _issue(report, 'missing_values').severity == 'critical'


def test_summary_sheet_that_disagrees_is_warned(clean, as_of):
    summary = {**clean.summary, 'total_sales': clean.summary['total_sales'] + 100}
    report = validate_import(replace(clean, summary=summary), as_of=as_of)
    assert _issue(report, 'reconciliation').severity == 'warning'


def test_matching_summary_raises_no_reconciliation_issue(clean, as_of):
    assert 'reconciliation' not in _codes(validate_import(clean, as_of=as_of))


def test_estimated_costs_are_reported(clean, as_of):
    sales = clean.sales.copy()
    sales.loc[sales.index[-5:], 'cost_is_estimated'] = True
    report = validate_import(_with_sales(clean, sales), as_of=as_of)
    issue = _issue(report, 'estimated_costs')
    assert issue.count == 5


def test_missing_stock_sheet_is_noted_not_blocking(clean, as_of):
    report = validate_import(replace(clean, stock=None), as_of=as_of)
    assert report.ok
    assert _issue(report, 'no_stock_sheet').severity == 'info'


def test_old_stock_count_is_warned(clean, as_of):
    stock = clean.stock.copy()
    stock['count_date'] = as_of - pd.Timedelta(days=60)
    report = validate_import(replace(clean, stock=stock), as_of=as_of)
    assert _issue(report, 'stock_stale').severity == 'warning'


def test_sold_product_missing_from_stock_sheet_is_warned(clean, as_of):
    stock = clean.stock.iloc[1:].copy()
    report = validate_import(replace(clean, stock=stock), as_of=as_of)
    assert 'stock_missing_product' in _codes(report)


def test_text_report_is_plain_and_free_of_personal_data(clean, as_of):
    text = validate_import(clean, as_of=as_of).to_text()
    assert 'Import check' in text
    assert 'customer' not in text.lower()
