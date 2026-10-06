import pandas as pd
import pytest

from src.synthetic.generator import generate_workbook

SALES_COLUMNS = [
    'Date', 'Sale ID', 'Customer', 'Product', 'Category', 'Quantity',
    'Unit Price (AUD)', 'Sale Total (AUD)', 'Payment Method', 'Sales Channel',
    'Customer Type', 'Suburb', 'Festival / Occasion', 'Business Event',
]


def _sales(path) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name='Sales')


def test_workbook_has_expected_sheets(workbook_path):
    names = pd.ExcelFile(workbook_path).sheet_names
    assert names == ['Sales', 'Simple Summary', 'Buy Prices', 'Stock & Orders']


def test_sales_sheet_has_the_real_column_layout(workbook_path):
    assert list(_sales(workbook_path).columns) == SALES_COLUMNS


def test_generation_is_deterministic(make_workbook):
    first = make_workbook('a.xlsx', seed=3)
    second = make_workbook('b.xlsx', seed=3)
    assert _sales(first).equals(_sales(second))


def test_different_seeds_differ(make_workbook):
    first = make_workbook('a.xlsx', seed=3)
    second = make_workbook('b.xlsx', seed=4)
    assert not _sales(first).equals(_sales(second))


def test_volume_matches_a_small_shop(workbook_path):
    sales = _sales(workbook_path)
    weeks = (sales['Date'].max() - sales['Date'].min()).days / 7
    per_week = len(sales) / weeks
    assert 5 <= per_week <= 20


def test_every_refund_points_at_an_earlier_sale(workbook_path):
    sales = _sales(workbook_path)
    refunds = sales[sales['Sale ID'].str.endswith('-R')]
    assert len(refunds) > 0
    assert (refunds['Quantity'] < 0).all()
    ids = set(sales['Sale ID'])
    assert refunds['Sale ID'].str[:-2].isin(ids).all()


def test_totals_equal_quantity_times_price(workbook_path):
    sales = _sales(workbook_path)
    expected = sales['Quantity'] * sales['Unit Price (AUD)']
    assert (sales['Sale Total (AUD)'] - expected).abs().max() < 0.01


def test_festival_and_event_tags_exist(workbook_path):
    sales = _sales(workbook_path)
    assert sales['Festival / Occasion'].notna().any()
    assert sales['Business Event'].notna().any()


def test_buy_prices_cover_every_product_sold(workbook_path):
    sold = set(_sales(workbook_path)['Product'])
    prices = pd.read_excel(workbook_path, sheet_name='Buy Prices', header=3)
    assert sold <= set(prices['Product'].dropna())


def test_stock_sheet_has_one_row_per_product(workbook_path):
    stock = pd.read_excel(workbook_path, sheet_name='Stock & Orders')
    assert list(stock.columns) == [
        'Product', 'Stock On Hand', 'Count Date', 'Weeks To Arrive',
        'Min Order Qty', 'On Order',
    ]
    assert stock['Product'].is_unique


def test_summary_totals_match_the_sales_sheet(workbook_path):
    sales = _sales(workbook_path)
    summary = pd.read_excel(workbook_path, sheet_name='Simple Summary',
                            header=None)
    labels = dict(zip(summary[0], summary[1]))
    assert labels['Total sales (AUD, after refunds)'] == pytest.approx(
        sales['Sale Total (AUD)'].sum()
    )
    assert labels['Number of sales'] == (sales['Quantity'] > 0).sum()
    assert labels['Number of returns / refunds'] == (sales['Quantity'] < 0).sum()


COMMON_REAL_FIRST_NAMES = {
    'Anita', 'Bina', 'Chitra', 'Dipa', 'Esha', 'Farah', 'Gita', 'Hena',
    'Indira', 'Jaya', 'Kabir', 'Lata', 'Mina', 'Nila', 'Omar', 'Priya',
    'Rina', 'Sima', 'Tara', 'Usha', 'Vikram', 'Wasim', 'Zara', 'Arjun',
    'Rahim', 'Sunita', 'Tanvir', 'Mitu', 'Nasrin', 'Rafiq', 'Rakesh',
    'Sanjay', 'Pooja', 'Munni', 'Nasir', 'Kakoli', 'Ayesha', 'Fatima',
    'Sarah', 'Emma', 'Olivia', 'John', 'David', 'Michael', 'Sophie',
}


def test_demo_first_names_are_invented_not_common_real_names():
    from src.synthetic.generator import FIRST_NAMES
    assert len(FIRST_NAMES) >= 20
    assert COMMON_REAL_FIRST_NAMES.isdisjoint(FIRST_NAMES)


def test_customer_names_are_invented_from_a_fixed_pool(workbook_path):
    names = _sales(workbook_path)['Customer'].dropna()
    assert names.str.match(r'^[A-Z][a-z]+ [A-Z]\.$').all()


@pytest.mark.parametrize('problem', [
    'duplicate_id', 'orphan_refund', 'unknown_product', 'blank_total',
    'bad_total',
])
def test_problems_can_be_injected(make_workbook, problem):
    clean = _sales(make_workbook('clean.xlsx', seed=5))
    dirty = _sales(make_workbook('dirty.xlsx', seed=5, problems={problem}))
    assert not clean.equals(dirty)


def test_unknown_problem_name_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        generate_workbook(tmp_path / 'x.xlsx', problems={'nonsense'})
