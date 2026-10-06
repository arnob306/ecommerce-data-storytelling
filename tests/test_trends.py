import pandas as pd
import pytest
from test_metrics import make_sales

from src.metrics.trends import weekly_series

END = pd.Timestamp('2026-01-01')
DAY = pd.Timedelta(days=1)


def test_weeks_are_seven_day_buckets_ending_on_the_end_date():
    sales = make_sales([
        {'date': END, 'qty': 1, 'price': 10},
        {'date': END - 7 * DAY, 'qty': 2, 'price': 10},
    ])
    series = weekly_series(sales, END, weeks=2)
    assert list(series['sales']) == [20, 10]
    assert series.index[-1] == END - 6 * DAY
    assert series.index[0] == END - 13 * DAY


def test_empty_weeks_are_zero_not_missing():
    sales = make_sales([{'date': END, 'qty': 1, 'price': 10}])
    series = weekly_series(sales, END, weeks=3)
    assert list(series['sales']) == [0, 0, 10]
    assert list(series['units']) == [0, 0, 1]


def test_refunds_reduce_sales_and_units():
    sales = make_sales([
        {'date': END, 'qty': 3, 'price': 10},
        {'date': END, 'qty': -1, 'price': 10},
    ])
    series = weekly_series(sales, END, weeks=1)
    assert series['sales'].iloc[0] == 20
    assert series['units'].iloc[0] == 2


def test_profit_ignores_sales_without_a_buy_price():
    sales = make_sales([
        {'date': END, 'qty': 1, 'price': 10, 'cost': 4},
        {'date': END, 'qty': 1, 'price': 50, 'cost': None},
    ])
    series = weekly_series(sales, END, weeks=1)
    assert series['sales'].iloc[0] == 60
    assert series['profit'].iloc[0] == pytest.approx(6)


def test_data_older_than_the_window_is_left_out():
    sales = make_sales([{'date': END - 30 * DAY, 'qty': 1, 'price': 10}])
    assert weekly_series(sales, END, weeks=2)['sales'].sum() == 0


def test_the_input_is_not_modified():
    sales = make_sales([{'date': END, 'qty': 1, 'price': 10}])
    before = sales.copy()
    weekly_series(sales, END, weeks=1)
    pd.testing.assert_frame_equal(sales, before)
