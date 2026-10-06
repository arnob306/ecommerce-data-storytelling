"""
The weekly summary she reads.

Everything here is plain arithmetic and templates - no LLM - so the numbers
are reproducible and her data never leaves the machine. The report answers
two questions: "what should I reorder?" and "which products make money?".
"""

import html
from dataclasses import dataclass
from typing import Optional, Tuple

import pandas as pd

from src.adapters.boutique_xlsx import WorkbookData
from src.metrics.patterns import festival_uplift
from src.metrics.products import product_performance
from src.metrics.reorder import reorder_suggestions
from src.validation.report import ImportReport

CURRENCY = '$'
WEEK_DAYS = 7
USUAL_WEEKS = 8
YEAR_SHIFT_DAYS = 364  # same weekday one year earlier
LOOKBACK_DAYS = 364
MAX_REORDER_LINES = 8
TOP_EARNERS = 5
SMALL_EARNERS = 3
COMING_UP_DAYS = 56
MIN_UPLIFT_TO_MENTION = 1.5
MAX_UPLIFT_CATEGORIES = 2


@dataclass(frozen=True)
class ReorderLine:
    product: str
    order_qty: int
    stock_now: int
    units_per_week: float
    lead_weeks: int
    confidence: str
    note: str
    on_order: int = 0


@dataclass(frozen=True)
class MoneyLine:
    product: str
    profit: float
    margin: Optional[float]
    units_sold: int


@dataclass(frozen=True)
class WeeklyReport:
    data_through: pd.Timestamp
    week_start: pd.Timestamp
    week_end: pd.Timestamp
    sales_this_week: float
    sales_count_this_week: int
    usual_week_sales: Optional[float]
    sales_last_year: Optional[float]
    profit_this_week: Optional[float]
    refunds_this_week: int
    reorder: Tuple[ReorderLine, ...]
    reorder_status: str  # 'orders' | 'nothing' | 'no_stock_sheet'
    coming_up: Tuple[str, ...]
    top_earners: Tuple[MoneyLine, ...]
    small_earners: Tuple[MoneyLine, ...]
    overall_margin: Optional[float]
    data_notes: Tuple[str, ...]
    trusted: bool


# --- building --------------------------------------------------------------

def _between(sales: pd.DataFrame, start, end) -> pd.DataFrame:
    return sales[(sales['date'] >= start) & (sales['date'] <= end)]


def _usual_week(sales, week_start) -> Optional[float]:
    """Average weekly sales over the 8 weeks before this one, if we have them."""
    day = pd.Timedelta(days=1)
    start = week_start - USUAL_WEEKS * WEEK_DAYS * day
    if sales['date'].min() > start:
        return None
    before = _between(sales, start, week_start - day)
    return float(before['line_total'].sum() / USUAL_WEEKS)


def _weekly_totals(sales, week_start, week_end) -> dict:
    day = pd.Timedelta(days=1)
    this_week = _between(sales, week_start, week_end)
    year_start = week_start - YEAR_SHIFT_DAYS * day
    last_year = (
        _between(sales, year_start, week_end - YEAR_SHIFT_DAYS * day)['line_total'].sum()
        if sales['date'].min() <= year_start else None
    )
    costed = this_week[this_week['unit_cost'].notna()]
    profit = (
        float((costed['line_total'] - costed['quantity'] * costed['unit_cost']).sum())
        if not costed.empty else None
    )
    return {
        'sales_this_week': float(this_week['line_total'].sum()),
        'sales_count_this_week': int((this_week['quantity'] > 0).sum()),
        'usual_week_sales': _usual_week(sales, week_start),
        'sales_last_year': None if last_year is None else float(last_year),
        'profit_this_week': profit,
        'refunds_this_week': int((this_week['quantity'] < 0).sum()),
    }


def _reorder_lines(data, as_of, calendar, uplift):
    if data.stock is None:
        return (), 'no_stock_sheet'
    suggestions = reorder_suggestions(
        data.sales, data.stock, as_of, calendar=calendar, uplift=uplift)
    needed = suggestions[suggestions['order_qty'] > 0].head(MAX_REORDER_LINES)
    lines = tuple(
        ReorderLine(r.product, int(r.order_qty), int(r.stock_now),
                    float(r.units_per_week), int(r.lead_weeks),
                    r.confidence, r.note, int(r.on_order))
        for r in needed.itertuples()
    )
    return lines, ('orders' if lines else 'nothing')


def _festival_effect(uplift: pd.DataFrame, name: str) -> str:
    rows = uplift[
        (uplift['festival'] == name) & (uplift['uplift'] >= MIN_UPLIFT_TO_MENTION)
    ].sort_values('uplift', ascending=False).head(MAX_UPLIFT_CATEGORIES)
    if rows.empty:
        return ''
    parts = [f'{r.category} (about {r.uplift:.1f}x)' for r in rows.itertuples()]
    return ' Usually sells faster: ' + ', '.join(parts) + '.'


def _coming_up(calendar, uplift, today) -> Tuple[str, ...]:
    horizon = today + pd.Timedelta(days=COMING_UP_DAYS)
    lines = []
    for window in sorted(calendar, key=lambda w: w.start):
        if window.end < today or window.start > horizon:
            continue
        days = (window.start - today).days
        if days > 0:
            lead = f'{window.name} starts in {days} days ({window.start:%d %b}).'
        else:
            lead = f'{window.name} is on now (until {window.end:%d %b}).'
        lines.append(lead + _festival_effect(uplift, window.name))
    return tuple(lines)


def _money_line(row) -> MoneyLine:
    margin = None if pd.isna(row.margin) else float(row.margin)
    return MoneyLine(row.Index, float(row.profit), margin, int(row.units_sold))


def _earners(sales, data_through):
    start = data_through - pd.Timedelta(days=LOOKBACK_DAYS)
    perf = product_performance(sales, start=start)
    perf = perf[perf['profit'].notna()]
    top = perf.head(TOP_EARNERS)
    sold = perf[perf['units_sold'] > 0].sort_values('profit')
    small = sold[~sold.index.isin(top.index)].head(SMALL_EARNERS)
    revenue = perf['revenue_costed'].sum()
    margin = float(perf['profit'].sum() / revenue) if revenue > 0 else None
    return (
        tuple(_money_line(r) for r in top.itertuples()),
        tuple(_money_line(r) for r in small.itertuples()),
        margin,
    )


def build_weekly_report(
    data: WorkbookData,
    import_report: ImportReport,
    today=None,
    calendar=None,
) -> WeeklyReport:
    """Assemble the figures for the 7 days ending at the newest sale."""
    sales = data.sales
    today = pd.Timestamp(today if today is not None else pd.Timestamp.today()).normalize()
    data_through = sales['date'].max().normalize()
    week_start = data_through - pd.Timedelta(days=WEEK_DAYS - 1)
    calendar = list(calendar or [])
    uplift = festival_uplift(sales)

    reorder, status = _reorder_lines(data, data_through, calendar, uplift)
    top, small, margin = _earners(sales, data_through)
    notes = tuple(
        issue.message for issue in import_report.issues
        if issue.severity in ('critical', 'warning')
    )
    return WeeklyReport(
        data_through=data_through, week_start=week_start, week_end=data_through,
        **_weekly_totals(sales, week_start, data_through),
        reorder=reorder, reorder_status=status,
        coming_up=_coming_up(calendar, uplift, today),
        top_earners=top, small_earners=small, overall_margin=margin,
        data_notes=notes, trusted=import_report.ok,
    )


# --- wording ---------------------------------------------------------------

def _money(value: float) -> str:
    sign = '-' if value < 0 else ''
    return f'{sign}{CURRENCY}{abs(value):,.0f}'


def _compare(now: float, before: float, label: str) -> str:
    gap = now - before
    if round(abs(gap)) == 0:
        return f'the same as {label}'
    direction = 'more' if gap > 0 else 'less'
    return f'{_money(abs(gap))} {direction} than {label}'


def _this_week_text(r: WeeklyReport) -> str:
    text = (
        f'You sold {_money(r.sales_this_week)} across {r.sales_count_this_week} '
        f'sales in the last 7 days ({r.week_start:%d %b} to {r.week_end:%d %b}).'
    )
    if r.usual_week_sales is not None:
        usual = f'a usual week (about {_money(r.usual_week_sales)})'
        text += f' That is {_compare(r.sales_this_week, r.usual_week_sales, usual)}.'
    if r.sales_last_year:
        text += (
            f' The same week last year was {_money(r.sales_last_year)}.'
            ' Single weeks vary a lot in a small shop, so look at the trend.'
        )
    if r.profit_this_week is not None:
        text += f' Estimated profit: {_money(r.profit_this_week)}.'
    if r.refunds_this_week:
        text += f' Refunds: {r.refunds_this_week}.'
    return text


def _reorder_bullet(line: ReorderLine) -> str:
    stock = f'{line.stock_now} left'
    if line.on_order:
        stock += f', {line.on_order} on order'
    text = (
        f'Order {line.order_qty} x {line.product} ({stock}, '
        f'selling about {line.units_per_week:.1f} a week, a shipment takes '
        f'{line.lead_weeks} weeks).'
    )
    if line.note:
        text += f' {line.note}.'
    if line.confidence == 'low':
        text += ' Not many recent sales, so treat this as a rough guess.'
    return text


def _money_bullet(line: MoneyLine) -> str:
    margin = f', {line.margin * 100:.0f}% margin' if line.margin is not None else ''
    return f'{line.product}: {_money(line.profit)} profit{margin}, {line.units_sold} sold.'


def _sections(r: WeeklyReport) -> list:
    """(title, intro, bullets) for each part of the report."""
    if r.reorder_status == 'no_stock_sheet':
        reorder = ("Reorder advice is off. Add a 'Stock & Orders' sheet to the "
                   'workbook (stock on hand, count date, weeks for a shipment '
                   'to arrive, minimum order) and it will switch on.', ())
    elif r.reorder_status == 'nothing':
        reorder = ('Nothing needs ordering right now.', ())
    else:
        reorder = (None, tuple(_reorder_bullet(l) for l in r.reorder))
    money_intro = None
    if r.overall_margin is not None:
        money_intro = f'Overall margin over the last 12 months: {r.overall_margin * 100:.0f}%.'
    sections = [
        ('This week', _this_week_text(r), ()),
        ('Reorder this week', reorder[0], reorder[1]),
    ]
    if r.coming_up:
        sections.append(('Coming up', None, r.coming_up))
    sections.append((
        "What's making money (last 12 months)", money_intro,
        tuple(_money_bullet(l) for l in r.top_earners),
    ))
    if r.small_earners:
        sections.append((
            'Small earners', 'These made the least profit in the last 12 months:',
            tuple(_money_bullet(l) for l in r.small_earners),
        ))
    if r.data_notes:
        sections.append(('Things to check in the data', None, r.data_notes))
    return sections


UNTRUSTED_BANNER = (
    'These numbers are NOT TRUSTED: the data has problems that could make '
    'them wrong. See "Things to check in the data" below.'
)


def subject(r: WeeklyReport) -> str:
    return f'Boutique weekly summary - week to {r.week_end:%d %b %Y}'


def _headline(r: WeeklyReport) -> str:
    return f'Data through {r.data_through:%a %d %b %Y}'


def render_text(r: WeeklyReport) -> str:
    """Plain-text version of the report."""
    lines = ['Boutique weekly summary', _headline(r), '']
    if not r.trusted:
        lines += [UNTRUSTED_BANNER, '']
    for title, intro, bullets in _sections(r):
        lines.append(title)
        if intro:
            lines.append(intro)
        lines += [f'- {b}' for b in bullets]
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


_STYLE = (
    'font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:1.5;'
    'color:#222;max-width:600px;margin:0 auto;padding:16px;'
)


def render_html(r: WeeklyReport) -> str:
    """Self-contained HTML (inline styles, no links or images)."""
    esc = html.escape
    parts = [
        f'<div style="{_STYLE}">',
        '<h1 style="font-size:22px;margin:0 0 4px;">Boutique weekly summary</h1>',
        f'<p style="color:#666;margin:0 0 16px;">{esc(_headline(r))}</p>',
    ]
    if not r.trusted:
        parts.append(
            '<p style="background:#fde8e8;border:1px solid #c0392b;padding:12px;'
            f'border-radius:6px;">{esc(UNTRUSTED_BANNER)}</p>')
    for title, intro, bullets in _sections(r):
        parts.append(f'<h2 style="font-size:18px;margin:20px 0 6px;">{esc(title)}</h2>')
        if intro:
            parts.append(f'<p style="margin:0 0 6px;">{esc(intro)}</p>')
        if bullets:
            items = ''.join(f'<li style="margin-bottom:6px;">{esc(b)}</li>' for b in bullets)
            parts.append(f'<ul style="padding-left:20px;margin:0;">{items}</ul>')
    parts.append('</div>')
    body = '\n'.join(parts)
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{esc(subject(r))}</title></head><body>{body}</body></html>'
    )
