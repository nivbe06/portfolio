{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key=['tenant_id', 'fired_on', 'campaign_id', 'effect_type', 'profile_segment']
) }}

with src as (
    select * from {{ ref('int_session_campaign_lineage') }}
    {% if is_incremental() %}
    where fired_on >= (select coalesce(max(fired_on), '1900-01-01') - interval 3 day from {{ this }})
    {% endif %}
)

select
    tenant                          as tenant_id,
    fired_on,
    campaign_id,
    effect_type,
    profile_segment,
    count(*)                        as effects_fired,
    sum(discount_value)             as discount_value,
    sum(points)                     as points_awarded,
    count(distinct session_id)      as sessions_with_effect,
    bool_or(is_monetary)            as is_monetary
from src
group by 1, 2, 3, 4, 5
