with source as (
    select * from {{ source('public', 'raw_transactions') }}
),

cleaned as (
    select
        id,
        invoice_no,
        stock_code,
        description,
        quantity,
        invoice_date,
        unit_price,
        customer_id,
        country,
        quantity * unit_price as line_total,
        date_trunc('week', invoice_date)::date as week_start
    from source
    where quantity > 0
      and unit_price > 0
)

select * from cleaned