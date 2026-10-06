"""
A one-page, phone-friendly dashboard.

Plain HTML and inline SVG: no scripts, no links, no images, no network calls,
so it can be opened from a file or an email attachment. It shows the same
figures as the weekly summary (built from the same ``WeeklyReport``) plus a
weekly sales chart. Only totals are drawn; no customer details are available
here.

Look: indigo and amber on cool paper, with a woven border stripe like the
edge of a saree. Colours were checked with the dataviz palette validator in
both light and dark mode.
"""

import html
from typing import Iterable, Optional

import pandas as pd

from src.reports.weekly import (
    UNTRUSTED_BANNER,
    MoneyLine,
    ReorderLine,
    WeeklyReport,
    money,
    money_bullet,
)

WEEKS_SHOWN = 26
CHART_WIDTH = 360
PLOT_HEIGHT = 120
CHART_HEIGHT = 150
LABEL_ROOM = 16  # space above the tallest bar for its value label
MAX_BAR_WIDTH = 24
BAR_GAP = 3
MIN_BAR_HEIGHT = 2
MIN_MONTH_GAP = 34  # keeps month names from touching
MIN_LABEL_GAP_WEEKS = 4
MIN_FILL_PERCENT = 2.0
METER_HEADROOM = 1.25

_CSS = (
    ':root{--paper:#f5f6fa;--ink:#1c2147;--ink2:#464b70;--muted:#666b8f;'
    '--rule:#d9dcea;--indigo:#3b4ba8;--amber:#c97c00;--loss:#b3382c;'
    '--warn:#fbe9e7}'
    '@media (prefers-color-scheme:dark){:root{--paper:#14172b;--ink:#eef0fa;'
    '--ink2:#b9bedd;--muted:#8e94ba;--rule:#2a2f52;--indigo:#6f80e8;'
    '--amber:#c48410;--loss:#d8604f;--warn:#3a1f22}}'
    '*{box-sizing:border-box}'
    'body{margin:0;background:var(--paper);color:var(--ink);'
    'font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;'
    'font-size:16px;line-height:1.5}'
    '.paar{height:14px;background:'
    'linear-gradient(var(--amber),var(--amber)) 0 2px/100% 2px no-repeat,'
    'linear-gradient(var(--indigo),var(--indigo)) 0 6px/100% 4px no-repeat,'
    'linear-gradient(var(--amber),var(--amber)) 0 12px/100% 2px no-repeat}'
    'main{max-width:640px;margin:0 auto;padding:20px 16px 40px}'
    'h1,h2{font-family:Georgia,"Times New Roman",serif;font-weight:700;'
    'line-height:1.2}'
    'h1{font-size:26px;margin:0 0 2px}'
    'h2{font-size:20px;margin:0 0 12px}'
    'section{border-top:1px solid var(--rule);padding-top:20px;margin-top:28px}'
    '.when{color:var(--muted);margin:0 0 20px}'
    '.hero{margin:0}'
    '.hero-label{margin:0;color:var(--ink2)}'
    '.hero-number{margin:0;font-size:56px;font-weight:700;line-height:1.1;'
    'letter-spacing:-0.02em;font-variant-numeric:lining-nums tabular-nums}'
    '.hero-line{margin:6px 0 0;color:var(--ink2);max-width:34em}'
    '.banner{border-left:4px solid var(--loss);background:var(--warn);'
    'padding:12px 14px;margin:0 0 20px}'
    'svg{width:100%;height:auto;display:block}'
    '.bar{fill:var(--indigo)}.bar:hover{opacity:.75}'
    '.bar.latest{fill:var(--amber)}'
    '.axis{stroke:var(--rule);stroke-width:1}'
    '.tick,.val{fill:var(--ink2);font-size:10px;'
    'font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}'
    '.val{font-weight:700;fill:var(--ink)}'
    '.note{color:var(--muted);font-size:14px;margin:8px 0 0}'
    'details{margin-top:12px}'
    'summary{cursor:pointer;color:var(--indigo);font-weight:600}'
    'summary:focus-visible{outline:2px solid var(--indigo);outline-offset:3px}'
    'table{border-collapse:collapse;width:100%;margin-top:8px;'
    'font-variant-numeric:tabular-nums}'
    'th,td{text-align:right;padding:6px 4px;border-bottom:1px solid var(--rule)}'
    'th:first-child,td:first-child{text-align:left}'
    'ul{list-style:none;padding:0;margin:0}'
    '.plain li{padding:8px 0 8px 12px;border-left:3px solid var(--rule);'
    'margin-bottom:8px}'
    '.order{padding:0 0 18px}'
    '.order-head{display:flex;gap:10px;align-items:baseline}'
    '.order-qty{font-size:20px;font-weight:700;min-width:5.5em}'
    '.order-name{font-weight:600}'
    '.order-text{margin:2px 0 8px;color:var(--ink2);font-size:15px}'
    '.meter{position:relative;height:10px;background:var(--rule);'
    'border-radius:5px}'
    '.meter-fill{height:10px;border-radius:5px;background:var(--indigo)}'
    '.meter-fill.short{background:var(--amber)}'
    '.meter-mark{position:absolute;top:-4px;width:2px;height:18px;'
    'background:var(--ink)}'
    '.row{margin:0 0 14px}.row-text{font-size:15px}'
    '.track{background:var(--rule);border-radius:4px;margin-top:4px}'
    '.fill{height:8px;border-radius:4px;background:var(--indigo)}'
    '.fill.loss{background:var(--loss)}'
)


def _esc(value: object) -> str:
    return html.escape(str(value))


def _versus_usual(r: WeeklyReport) -> str:
    if r.usual_week_sales is None:
        return ''
    gap = r.sales_this_week - r.usual_week_sales
    if round(abs(gap)) == 0:
        return 'About the same as a usual week.'
    direction = 'more' if gap > 0 else 'less'
    return f'{money(abs(gap))} {direction} than a usual week.'


def _hero_line(r: WeeklyReport) -> str:
    parts = [_versus_usual(r)]
    if r.profit_this_week is not None:
        parts.append(f'Estimated profit {money(r.profit_this_week)}.')
    if r.overall_margin is not None:
        parts.append(f'Margin over the last 12 months: {r.overall_margin * 100:.0f}%.')
    return ' '.join(part for part in parts if part)


def _hero(r: WeeklyReport) -> str:
    return (
        '<p class="hero-label">Sold in the last 7 days</p>'
        f'<p class="hero-number">{_esc(money(r.sales_this_week))}</p>'
        f'<p class="hero-line">{_esc(_hero_line(r))}</p>'
    )


def _bar(index: int, week, value: float, top: float, slot: float, latest: bool) -> str:
    width = min(MAX_BAR_WIDTH, max(slot - BAR_GAP, 1))
    x = index * slot + (slot - width) / 2
    height = max(MIN_BAR_HEIGHT, value / top * (PLOT_HEIGHT - LABEL_ROOM)) if value > 0 else 0
    css = 'bar latest' if latest else 'bar'
    return (
        f'<rect class="{css}" data-week="{week:%Y-%m-%d}" x="{x:.1f}" '
        f'y="{PLOT_HEIGHT - height:.1f}" width="{width:.1f}" height="{height:.1f}" '
        f'rx="2"><title>Week of {week:%d %b}: {_esc(money(value))}</title></rect>'
    )


def _value_label(index: int, value: float, top: float, slot: float, text: str) -> str:
    height = value / top * (PLOT_HEIGHT - LABEL_ROOM)
    x = min(max(index * slot + slot / 2, 24), CHART_WIDTH - 24)
    return (f'<text class="val" x="{x:.1f}" y="{PLOT_HEIGHT - height - 5:.1f}" '
            f'text-anchor="middle">{_esc(text)}</text>')


def _month_ticks(weeks: pd.DatetimeIndex, slot: float) -> str:
    ticks, last_x, last_month = [], -MIN_MONTH_GAP, None
    for i, week in enumerate(weeks):
        if week.month != last_month and i * slot - last_x >= MIN_MONTH_GAP:
            ticks.append(f'<text class="tick" x="{i * slot:.1f}" '
                         f'y="{CHART_HEIGHT - 6}">{week:%b}</text>')
            last_x = i * slot
        last_month = week.month
    return ''.join(ticks)


def _chart_labels(values: list, top: float, slot: float) -> str:
    newest = len(values) - 1
    labels = [_value_label(newest, values[newest], top, slot, money(values[newest]))]
    best = max(range(len(values)), key=values.__getitem__)
    if values[best] > 0 and newest - best >= MIN_LABEL_GAP_WEEKS:
        labels.append(_value_label(best, values[best], top, slot, money(values[best])))
    return ''.join(labels)


def _sales_chart(series: pd.DataFrame) -> str:
    count = len(series)
    if count == 0:
        return '<p>No sales to chart yet.</p>'
    values = [float(v) for v in series['sales']]
    slot = CHART_WIDTH / count
    top = max(max(values), 1.0)
    bars = ''.join(
        _bar(i, week, value, top, slot, latest=i == count - 1)
        for i, (week, value) in enumerate(zip(series.index, values))
    )
    label = f'Weekly sales for the last {count} weeks, best week {money(max(values))}'
    return (
        f'<svg viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" role="img" '
        f'aria-label="{_esc(label)}">{bars}'
        f'<line class="axis" x1="0" x2="{CHART_WIDTH}" y1="{PLOT_HEIGHT}" '
        f'y2="{PLOT_HEIGHT}"/>{_month_ticks(series.index, slot)}'
        f'{_chart_labels(values, top, slot)}</svg>'
        '<p class="note">One bar per week. The amber bar is the last 7 days.</p>'
        f'{_table_view(series)}'
    )


def _table_view(series: pd.DataFrame) -> str:
    rows = ''.join(
        f'<tr><td>{week:%d %b %Y}</td><td>{_esc(money(row.sales))}</td>'
        f'<td>{_esc(money(row.profit))}</td></tr>'
        for week, row in series.iloc[::-1].iterrows()
    )
    return (
        '<details><summary>Show as a table</summary><table><thead><tr>'
        '<th scope="col">Week starting</th><th scope="col">Sales</th>'
        '<th scope="col">Profit</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></details>'
    )


def _cover_weeks(line: ReorderLine) -> Optional[float]:
    return line.stock_now / line.units_per_week if line.units_per_week > 0 else None


def _meter(cover: float, lead: int) -> str:
    scale = max(cover, lead) * METER_HEADROOM or 1.0
    short = ' short' if cover < lead else ''
    return (
        f'<div class="meter"><div class="meter-fill{short}" '
        f'style="width:{cover / scale * 100:.0f}%"></div>'
        f'<div class="meter-mark" style="left:{lead / scale * 100:.0f}%"></div></div>'
    )


def _weeks(count: float) -> str:
    whole = round(count)
    return f'{whole} week' if whole == 1 else f'{whole} weeks'


def _order_text(line: ReorderLine, cover: Optional[float]) -> str:
    if cover is None:
        return f'{line.stock_now} left and no recent sales.'
    text = (f'{line.stock_now} left, selling about {line.units_per_week:.1f} a week. '
            f'That lasts {_weeks(cover)}; a shipment takes {_weeks(line.lead_weeks)}.')
    if line.on_order:
        text += f' {line.on_order} already on order.'
    if line.note:
        text += f' {line.note}.'
    if line.confidence == 'low':
        text += ' Not many recent sales, so treat this as a rough guess.'
    return text


def _order_row(line: ReorderLine) -> str:
    cover = _cover_weeks(line)
    attrs = f'data-reorder="{_esc(line.product)}"'
    meter = ''
    if cover is not None:
        attrs += f' data-cover-weeks="{cover:.1f}" data-lead-weeks="{line.lead_weeks}"'
        meter = _meter(cover, line.lead_weeks)
    return (
        f'<li class="order" {attrs}><div class="order-head">'
        f'<span class="order-qty">Order {line.order_qty}</span>'
        f'<span class="order-name">{_esc(line.product)}</span></div>'
        f'<p class="order-text">{_esc(_order_text(line, cover))}</p>{meter}</li>'
    )


def _reorder(r: WeeklyReport) -> str:
    if r.reorder_status == 'no_stock_sheet':
        return ("<p>Reorder advice is off. Add a 'Stock &amp; Orders' sheet to "
                'the workbook and it will switch on.</p>')
    if r.reorder_status == 'nothing':
        return '<p>Nothing needs ordering right now.</p>'
    note = ('<p class="note">The bar is how long stock lasts. The line marks '
            'when a new shipment would arrive; amber means stock runs out first.</p>')
    return f'<ul>{"".join(_order_row(line) for line in r.reorder)}</ul>{note}'


def _profit_rows(lines: Iterable[MoneyLine]) -> str:
    lines = list(lines)
    if not lines:
        return '<p>No costed sales yet.</p>'
    scale = max(abs(line.profit) for line in lines) or 1.0
    rows = []
    for line in lines:
        width = max(MIN_FILL_PERCENT, abs(line.profit) / scale * 100)
        tone = ' loss' if line.profit < 0 else ''
        rows.append(
            f'<div class="row" data-product="{_esc(line.product)}">'
            f'<span class="row-text">{_esc(money_bullet(line))}</span>'
            f'<div class="track"><div class="fill{tone}" '
            f'style="width:{width:.0f}%"></div></div></div>'
        )
    return ''.join(rows)


def _list(items: Iterable[str]) -> str:
    entries = ''.join(f'<li>{_esc(item)}</li>' for item in items)
    return f'<ul class="plain">{entries}</ul>' if entries else ''


def _section(title: str, body: str) -> str:
    return f'<section><h2>{_esc(title)}</h2>{body}</section>' if body else ''


def _banner(r: WeeklyReport) -> str:
    return f'<p class="banner">{_esc(UNTRUSTED_BANNER)}</p>' if not r.trusted else ''


def render_dashboard(r: WeeklyReport, series: pd.DataFrame) -> str:
    """The whole dashboard as one self-contained HTML string."""
    earners = (*r.top_earners, *r.small_earners)
    body = ''.join([
        '<h1>Boutique dashboard</h1>',
        f'<p class="when">Data through {_esc(f"{r.data_through:%a %d %b %Y}")}</p>',
        _banner(r),
        f'<div class="hero">{_hero(r)}</div>',
        _section('Weekly sales', _sales_chart(series)),
        _section('Reorder this week', _reorder(r)),
        _section('Coming up', _list(r.coming_up)),
        _section('Profit by product (last 12 months)', _profit_rows(earners)),
        _section('Things to check in the data', _list(r.data_notes)),
    ])
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>Boutique dashboard</title><style>{_CSS}</style></head>'
        f'<body><div class="paar" aria-hidden="true"></div><main>{body}</main>'
        '</body></html>'
    )
