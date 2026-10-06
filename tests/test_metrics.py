import pandas as pd
import pytest

from src.metrics.calendar import FestivalWindow, load_calendar, upcoming
from src.metrics.patterns import (
    day_of_week_pattern,
    festival_uplift,
    festival_windows,
)
from src.metrics.products import product_performance
from src.metrics.reorder import reorder_suggestions
from src.metrics.velocity import CensoredWindow, censored_windows, weekly_velocity
from src.schema import STANDARD_COLUMNS

AS_OF = pd.Timestamp('2026-01-01')


def make_sales(rows) -> pd.DataFrame:
    """Build a standard-schema frame from short dicts."""
    out = []
    for i, row in enumerate(rows):
        qty = row.get('qty', 1)
        price = row.get('price', 10.0)
        out.append({
            'date': pd.Timestamp(row['date']),
            'sale_id': f"T{i:05d}{'-R' if qty < 0 else ''}",
            'refund_of': row.get('refund_of'),
            'product': row.get('product', 'P'),
            'category': row.get('category', 'Saree'),
            'quantity': qty,
            'unit_price': price,
            'line_total': qty * price,
            'unit_cost': row.get('cost', 4.0),
            'cost_is_estimated': False,
            'customer_id': None,
            'festival': row.get('festival'),
            'event': row.get('event'),
            'channel': None,
        })
    return pd.DataFrame(out, columns=STANDARD_COLUMNS)


def weekly_sales(count=13, **kwargs):
    """One sale a week, newest on AS_OF."""
    return make_sales([
        {'date': AS_OF - pd.Timedelta(days=7 * k), **kwargs}
        for k in range(count)
    ])


# --- product performance ---------------------------------------------------

def test_profit_and_margin_are_computed_per_product():
    sales = make_sales([
        {'date': '2026-01-01', 'product': 'A', 'qty': 2, 'price': 10, 'cost': 4},
        {'date': '2026-01-02', 'product': 'B', 'qty': 1, 'price': 100, 'cost': 80},
    ])
    result = product_performance(sales)
    assert result.loc['A', 'revenue'] == 20
    assert result.loc['A', 'profit'] == 12
    assert result.loc['A', 'margin'] == pytest.approx(0.6)
    assert result.loc['B', 'margin'] == pytest.approx(0.2)


def test_products_are_ranked_by_profit():
    sales = make_sales([
        {'date': '2026-01-01', 'product': 'A', 'price': 10, 'cost': 4},
        {'date': '2026-01-01', 'product': 'B', 'price': 100, 'cost': 80},
    ])
    assert list(product_performance(sales).index) == ['B', 'A']


def test_refunds_reduce_revenue_profit_and_set_the_refund_rate():
    sales = make_sales([
        {'date': '2026-01-01', 'qty': 2, 'price': 10, 'cost': 4},
        {'date': '2026-01-05', 'qty': -1, 'price': 10, 'cost': 4},
    ])
    row = product_performance(sales).loc['P']
    assert row['revenue'] == 10
    assert row['profit'] == 6
    assert row['units_sold'] == 2
    assert row['units_refunded'] == 1
    assert row['refund_rate'] == pytest.approx(0.5)


def test_sales_without_a_cost_are_left_out_of_profit_only():
    sales = make_sales([
        {'date': '2026-01-01', 'price': 10, 'cost': 4},
        {'date': '2026-01-02', 'price': 10, 'cost': float('nan')},
    ])
    row = product_performance(sales).loc['P']
    assert row['revenue'] == 20
    assert row['profit'] == 6
    assert row['margin'] == pytest.approx(0.6)


def test_date_window_limits_the_figures():
    sales = make_sales([
        {'date': '2025-06-01', 'price': 10},
        {'date': '2026-01-01', 'price': 10},
    ])
    result = product_performance(sales, start='2025-12-01')
    assert result.loc['P', 'revenue'] == 10


# --- velocity --------------------------------------------------------------

def test_velocity_is_units_per_week_over_the_window():
    result = weekly_velocity(weekly_sales(13), AS_OF, weeks=13)
    assert result.loc['P', 'units'] == 13
    assert result.loc['P', 'units_per_week'] == pytest.approx(1.0)


def test_refunds_do_not_reduce_demand():
    sales = pd.concat([
        weekly_sales(13),
        make_sales([{'date': '2025-12-30', 'qty': -1}]),
    ], ignore_index=True)
    assert weekly_velocity(sales, AS_OF).loc['P', 'units'] == 13


def test_sales_outside_the_window_are_ignored():
    sales = weekly_sales(20)
    assert weekly_velocity(sales, AS_OF, weeks=13).loc['P', 'units'] == 13


def test_a_product_with_no_recent_sales_has_zero_velocity():
    sales = pd.concat([
        weekly_sales(13),
        make_sales([{'date': '2024-01-01', 'product': 'Old'}]),
    ], ignore_index=True)
    result = weekly_velocity(sales, AS_OF)
    assert result.loc['Old', 'units_per_week'] == 0


def test_censored_days_are_removed_from_the_denominator():
    window = CensoredWindow(
        AS_OF - pd.Timedelta(days=40), AS_OF - pd.Timedelta(days=15), 'P'
    )
    result = weekly_velocity(weekly_sales(13), AS_OF, weeks=13, windows=[window])
    assert result.loc['P', 'weeks_observed'] == pytest.approx((91 - 26) / 7)
    assert result.loc['P', 'units_per_week'] > 1.0


def test_censored_windows_come_from_event_labels():
    sales = make_sales([
        {'date': '2019-08-20', 'event': 'Silk Saree out of stock'},
        {'date': '2019-10-01', 'event': 'Silk Saree out of stock'},
        {'date': '2020-04-01', 'event': 'COVID lockdown'},
        {'date': '2020-06-01', 'event': 'COVID lockdown'},
        {'date': '2021-01-01', 'event': 'Price increase'},
    ])
    found = {(w.product, w.start, w.end) for w in censored_windows(sales)}
    assert found == {
        ('Silk Saree', pd.Timestamp('2019-08-20'), pd.Timestamp('2019-10-01')),
        (None, pd.Timestamp('2020-04-01'), pd.Timestamp('2020-06-01')),
    }


# --- patterns --------------------------------------------------------------

def test_day_of_week_shares_add_up_and_show_busy_days():
    sales = make_sales([
        {'date': '2025-12-27'}, {'date': '2025-12-20'}, {'date': '2025-12-13'},
        {'date': '2025-12-15'},
    ])
    result = day_of_week_pattern(sales, AS_OF)
    assert result['share'].sum() == pytest.approx(1.0)
    assert result['share'].idxmax() == 'Saturday'


def _festival_rows(label, start, days, per_day=1):
    return [
        {'date': pd.Timestamp(start) + pd.Timedelta(days=d), 'festival': label}
        for d in range(days) for _ in range(per_day)
    ]


def test_separate_bursts_of_one_festival_become_separate_windows():
    sales = make_sales(
        _festival_rows('Eid', '2024-04-10', 5)
        + _festival_rows('Eid', '2024-06-16', 3)
    )
    windows = festival_windows(sales)
    assert len(windows) == 2


def test_festival_labels_spread_across_months_are_not_a_window():
    spread = [
        {'date': pd.Timestamp('2024-01-01') + pd.Timedelta(days=5 * i),
         'festival': 'Wedding / Family Event'}
        for i in range(40)
    ]
    assert festival_windows(make_sales(spread)).empty


def _three_years_with_durga_puja():
    rows = []
    for year in (2022, 2023, 2024):
        for day in pd.date_range(f'{year}-01-01', f'{year}-12-31'):
            in_window = pd.Timestamp(f'{year}-10-10') <= day <= pd.Timestamp(f'{year}-10-20')
            for _ in range(3 if in_window else 1):
                rows.append({
                    'date': day,
                    'festival': 'Durga Puja' if in_window else None,
                })
    return make_sales(rows)


def test_festival_uplift_is_learned_from_labelled_history():
    result = festival_uplift(_three_years_with_durga_puja())
    row = result[(result['festival'] == 'Durga Puja')
                 & (result['category'] == 'Saree')].iloc[0]
    assert row['uplift'] == pytest.approx(3.0, abs=0.1)
    assert row['windows'] == 3


def test_uplift_needs_at_least_two_windows():
    sales = make_sales(
        [{'date': d} for d in pd.date_range('2024-01-01', '2024-12-31')]
        + _festival_rows('Durga Puja', '2024-10-10', 10, per_day=3)
    )
    assert festival_uplift(sales).empty


# --- festival calendar -----------------------------------------------------

def test_calendar_loads_and_filters_to_a_period(tmp_path):
    path = tmp_path / 'festivals.yaml'
    path.write_text(
        'festivals:\n'
        '  - name: Durga Puja\n    start: 2026-10-10\n    end: 2026-10-21\n',
        encoding='utf-8',
    )
    calendar = load_calendar(path)
    assert calendar == [FestivalWindow(
        'Durga Puja', pd.Timestamp('2026-10-10'), pd.Timestamp('2026-10-21'))]
    assert upcoming(calendar, pd.Timestamp('2026-10-01'), pd.Timestamp('2026-10-15'))
    assert not upcoming(calendar, pd.Timestamp('2026-10-01'), pd.Timestamp('2026-10-05'))


def test_shipped_calendar_has_future_festivals():
    calendar = load_calendar('config/festivals.yaml')
    assert any(w.end >= pd.Timestamp('2026-10-01') for w in calendar)
    assert all(w.start <= w.end for w in calendar)


# --- reorder suggestions ---------------------------------------------------

def stock_frame(on_hand=0, count_date=AS_OF, weeks=4, min_qty=1, product='P',
                on_order=0):
    return pd.DataFrame([{
        'product': product, 'stock_on_hand': on_hand,
        'count_date': pd.Timestamp(count_date), 'weeks_to_arrive': weeks,
        'min_order_qty': min_qty, 'on_order': on_order,
    }])


def _row(result, product='P'):
    return result.set_index('product').loc[product]


def test_reorder_covers_lead_time_plus_a_week_with_safety_stock():
    result = reorder_suggestions(weekly_sales(13), stock_frame(), AS_OF)
    row = _row(result)
    assert row['expected_demand'] == pytest.approx(5.0)
    assert row['safety_stock'] == 3
    assert row['order_qty'] == 8


def test_no_order_when_stock_already_covers_demand():
    result = reorder_suggestions(weekly_sales(13), stock_frame(on_hand=10), AS_OF)
    assert _row(result)['order_qty'] == 0


def test_stock_already_on_order_is_not_ordered_again():
    result = reorder_suggestions(
        weekly_sales(13), stock_frame(on_order=5), AS_OF)
    row = _row(result)
    assert row['on_order'] == 5
    assert row['order_qty'] == 3


def test_an_order_in_transit_that_covers_demand_means_no_new_order():
    result = reorder_suggestions(
        weekly_sales(13), stock_frame(on_order=20), AS_OF)
    assert _row(result)['order_qty'] == 0


def test_minimum_order_quantity_is_respected():
    result = reorder_suggestions(
        weekly_sales(13), stock_frame(min_qty=12), AS_OF)
    assert _row(result)['order_qty'] == 12


def test_stock_is_reduced_by_sales_since_the_count():
    stock = stock_frame(on_hand=8, count_date=AS_OF - pd.Timedelta(days=14))
    row = _row(reorder_suggestions(weekly_sales(13), stock, AS_OF))
    assert row['stock_now'] == 6
    assert row['order_qty'] == 2


def test_an_upcoming_festival_raises_the_order():
    calendar = [FestivalWindow(
        'Durga Puja', AS_OF + pd.Timedelta(days=1), AS_OF + pd.Timedelta(days=35))]
    uplift = pd.DataFrame([{
        'festival': 'Durga Puja', 'category': 'Saree', 'uplift': 3.0, 'windows': 3,
    }])
    result = reorder_suggestions(
        weekly_sales(13), stock_frame(), AS_OF, calendar=calendar, uplift=uplift)
    row = _row(result)
    assert row['expected_demand'] == pytest.approx(15.0)
    assert row['order_qty'] == 19
    assert 'Durga Puja' in row['note']


def test_few_recent_sales_are_marked_low_confidence():
    row = _row(reorder_suggestions(weekly_sales(3), stock_frame(), AS_OF))
    assert row['confidence'] == 'low'


def test_a_regular_seller_is_not_low_confidence():
    row = _row(reorder_suggestions(weekly_sales(13), stock_frame(), AS_OF))
    assert row['confidence'] == 'medium'


def test_no_stock_sheet_means_no_suggestions():
    result = reorder_suggestions(weekly_sales(13), None, AS_OF)
    assert result.empty
    assert 'order_qty' in result.columns


def test_products_with_no_recent_sales_are_not_reordered():
    sales = make_sales([{'date': '2024-01-01'}])
    row = _row(reorder_suggestions(sales, stock_frame(), AS_OF))
    assert row['order_qty'] == 0
    assert 'no recent sales' in row['note']


def test_largest_orders_come_first():
    sales = pd.concat([
        weekly_sales(13, product='A'), weekly_sales(13, product='B', qty=3),
    ], ignore_index=True)
    stock = pd.concat([
        stock_frame(product='A'), stock_frame(product='B')], ignore_index=True)
    result = reorder_suggestions(sales, stock, AS_OF)
    assert list(result['product']) == ['B', 'A']
