with base as (
    select * from {{ ref('stg_transactions') }}
)

select
    week_start,
    country,
    stock_code,
    COUNT(distinct invoice_no)                    as order_count,
    COUNT(distinct customer_id)                   as unique_customers,
    SUM(quantity)                                 as units_sold,
    SUM(line_total)                               as revenue,
    SUM(line_total) / NULLIF(COUNT(distinct invoice_no), 0)  as revenue_per_order,
    SUM(line_total) / NULLIF(COUNT(distinct customer_id), 0) as revenue_per_customer
from base
group by week_start, country, stock_code