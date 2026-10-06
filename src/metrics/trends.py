"""Weekly totals over time, for the dashboard's trend charts."""

import pandas as pd

WEEK_DAYS = 7
DEFAULT_WEEKS = 26
COLUMNS = ['sales', 'profit', 'units']


def weekly_series(sales: pd.DataFrame, end, weeks: int = DEFAULT_WEEKS) -> pd.DataFrame:
    """
    Sales, profit and units for each of the last ``weeks`` 7-day weeks.

    The newest week ends on ``end``; each row is labelled with its first day.
    Weeks with no sales are zero. Refunds reduce sales and units. Profit only
    counts sales that have a buy price, so a missing cost never inflates it.
    """
    end = pd.Timestamp(end).normalize()
    day = pd.Timedelta(days=1)
    first_day = end - (weeks * WEEK_DAYS - 1) * day
    starts = [
        end - (WEEK_DAYS * (k + 1) - 1) * day
        for k in range(weeks - 1, -1, -1)
    ]
    dates = sales['date'].dt.normalize()
    window = sales[(dates >= first_day) & (dates <= end)]

    weeks_back = (end - window['date'].dt.normalize()).dt.days // WEEK_DAYS
    labels = end - (WEEK_DAYS * weeks_back + WEEK_DAYS - 1) * day
    costed = window['unit_cost'].notna()
    profit = (
        window['line_total'] - window['quantity'] * window['unit_cost']
    ).where(costed, 0.0)

    totals = pd.DataFrame({
        'sales': window['line_total'].groupby(labels).sum(),
        'profit': profit.groupby(labels).sum(),
        'units': window['quantity'].groupby(labels).sum(),
    })
    index = pd.DatetimeIndex(starts, name='week_start')
    return totals.reindex(index, fill_value=0)[COLUMNS]
