from dataclasses import replace

import pytest
from test_report import _build

from src.adapters.boutique_xlsx import load_workbook_data
from src.metrics.trends import weekly_series
from src.reports.dashboard import WEEKS_SHOWN, render_dashboard
from src.reports.weekly import ReorderLine, money

SALT = 'unit-test-salt-0123456789'


@pytest.fixture(scope='module')
def built(workbook_path):
    data, report = _build(workbook_path)
    series = weekly_series(data.sales, report.data_through, WEEKS_SHOWN)
    return data, report, series


@pytest.fixture(scope='module')
def page(built):
    _, report, series = built
    return render_dashboard(report, series)


def test_page_is_a_mobile_friendly_html_document(page):
    assert page.startswith('<!DOCTYPE html>')
    assert 'name="viewport"' in page
    assert 'viewBox=' in page


def test_page_is_self_contained(page):
    lowered = page.lower()
    assert '<script' not in lowered
    assert 'http://' not in lowered and 'https://' not in lowered
    assert '<link' not in lowered and '<img' not in lowered


def test_one_bar_is_drawn_for_each_week(built, page):
    _, _, series = built
    assert page.count('data-week=') == len(series)


def test_headline_figures_are_shown(built, page):
    _, report, _ = built
    assert 'Boutique dashboard' in page
    assert f'{report.data_through:%d %b %Y}' in page


def test_reorder_lines_appear_when_there_is_a_stock_sheet(built, page):
    _, report, _ = built
    assert report.reorder_status in ('orders', 'nothing')
    for line in report.reorder:
        assert line.product in page


def test_missing_stock_sheet_is_explained(workbook_path):
    data, report = _build(workbook_path, drop_stock=True)
    series = weekly_series(data.sales, report.data_through, WEEKS_SHOWN)
    assert 'Stock & Orders' in render_dashboard(report, series).replace('&amp;', '&')


def test_untrusted_data_shows_a_warning_banner(built):
    _, report, series = built
    page = render_dashboard(replace(report, trusted=False), series)
    assert 'NOT TRUSTED' in page


def test_trusted_data_has_no_warning_banner(page):
    assert 'NOT TRUSTED' not in page


def test_product_names_are_html_escaped(built):
    _, report, series = built
    top = replace(report.top_earners[0], product='<b>Evil</b> & Co')
    page = render_dashboard(replace(report, top_earners=(top,)), series)
    assert '<b>Evil</b>' not in page
    assert '&lt;b&gt;Evil&lt;/b&gt; &amp; Co' in page


def test_no_customer_identifiers_appear(workbook_path, page):
    data = load_workbook_data(workbook_path, salt=SALT)
    for customer_id in data.sales['customer_id'].dropna().unique()[:200]:
        assert customer_id not in page


def test_an_empty_series_says_there_is_nothing_to_chart(built):
    _, report, series = built
    page = render_dashboard(report, series.iloc[0:0])
    assert 'No sales to chart yet' in page
    assert 'data-week=' not in page


def test_a_loss_making_product_gets_the_loss_bar(built):
    _, report, series = built
    losing = replace(report.top_earners[0], profit=-50.0)
    page = render_dashboard(replace(report, top_earners=(losing,)), series)
    assert 'class="fill loss"' in page


def test_nothing_to_order_is_stated_plainly(built):
    _, report, series = built
    page = render_dashboard(
        replace(report, reorder=(), reorder_status='nothing'), series)
    assert 'Nothing needs ordering right now' in page


def test_the_headline_is_this_weeks_sales(built, page):
    _, report, _ = built
    assert 'Sold in the last 7 days' in page
    assert money(report.sales_this_week) in page


def test_only_the_newest_week_is_highlighted(built, page):
    _, _, series = built
    assert page.count('class="bar latest"') == 1
    newest = f'class="bar latest" data-week="{series.index[-1]:%Y-%m-%d}"'
    assert newest in page


def test_a_table_view_lists_every_week(built, page):
    _, _, series = built
    assert '<details' in page
    assert page.count('<tr>') == len(series) + 1  # header row plus one per week


def test_dark_mode_colours_are_defined(page):
    assert 'prefers-color-scheme:dark' in page


def test_reorder_rows_compare_stock_cover_with_shipment_time(built):
    _, report, series = built
    line = ReorderLine(
        product='Test Saree', order_qty=8, stock_now=4, units_per_week=0.5,
        lead_weeks=7, confidence='good', note='')
    page = render_dashboard(
        replace(report, reorder=(line,), reorder_status='orders'), series)
    assert 'data-reorder="Test Saree"' in page
    assert 'data-cover-weeks="8.0"' in page
    assert 'data-lead-weeks="7"' in page


def test_stock_that_will_not_sell_has_no_cover_figure(built):
    _, report, series = built
    line = ReorderLine(
        product='Slow Saree', order_qty=2, stock_now=4, units_per_week=0.0,
        lead_weeks=7, confidence='low', note='no recent sales')
    page = render_dashboard(
        replace(report, reorder=(line,), reorder_status='orders'), series)
    assert 'data-reorder="Slow Saree"' in page
    assert 'data-cover-weeks' not in page


def test_one_week_is_not_pluralised(built):
    _, report, series = built
    line = ReorderLine(
        product='Fast Saree', order_qty=3, stock_now=1, units_per_week=1.0,
        lead_weeks=1, confidence='good', note='')
    page = render_dashboard(
        replace(report, reorder=(line,), reorder_status='orders'), series)
    assert 'lasts 1 week;' in page
    assert 'takes 1 week.' in page
    assert '1 weeks' not in page
