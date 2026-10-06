"""Standard schema that every source adapter maps into."""

STANDARD_COLUMNS = [
    'date',
    'sale_id',
    'refund_of',
    'product',
    'category',
    'quantity',
    'unit_price',
    'line_total',
    'unit_cost',
    'cost_is_estimated',
    'customer_id',
    'festival',
    'event',
    'channel',
]

STOCK_COLUMNS = [
    'product',
    'stock_on_hand',
    'count_date',
    'weeks_to_arrive',
    'min_order_qty',
    'on_order',
]

REFUND_SUFFIX = '-R'
