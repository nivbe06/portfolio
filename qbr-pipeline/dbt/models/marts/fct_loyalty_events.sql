{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key=['tenant_id', 'occurred_on']
) }}

with src as (
    select * from {{ ref('stg_loyalty_events') }}
    {% if is_incremental() %}
    where occurred_on >= (select coalesce(max(occurred_on), '1900-01-01') - interval 3 day from {{ this }})
    {% endif %}
)

select
    tenant                          as tenant_id,
    occurred_on,
    count(*)                        as loyalty_events,
    sum(points_issued)              as points_issued,
    sum(points_burned)              as points_burned,
    sum(points_issued) - sum(points_burned) as net_points_outstanding,
    count(distinct profile_id)      as distinct_members
from src
group by 1, 2
