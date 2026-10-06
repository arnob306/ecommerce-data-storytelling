with weekly as (
    select * from {{ ref('int_weekly_transactions') }}
)

select
    week_start,
    SUM(revenue)                                    as total_revenue,
    SUM(order_count)                                as order_count,
    SUM(units_sold)                                 as units_sold,
    SUM(unique_customers)                           as active_customers,
    SUM(revenue) / NULLIF(SUM(order_count), 0)      as revenue_per_order,
    SUM(revenue) / NULLIF(SUM(unique_customers), 0) as revenue_per_customer
from weekly
group by week_start
order by week_start