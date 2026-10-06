with anomalies as (
    select * from {{ source('public', 'anomalies') }}
),

root_causes as (
    select * from {{ source('public', 'root_causes') }}
),

top_drivers as (
    select
        anomaly_id,
        status,
        dimension        as top_dimension,
        segment_value    as top_segment,
        contribution_pct as top_contribution_pct
    from root_causes
    where segment_rank = 1
)

select
    a.id,
    a.kpi_name,
    a.anomaly_date,
    a.severity,
    a.confidence,
    a.actual_value,
    a.expected_value,
    a.deviation_pct,
    a.detection_methods,
    t.status,
    t.top_dimension,
    t.top_segment,
    t.top_contribution_pct
from anomalies a
left join top_drivers t
    on a.id = t.anomaly_id