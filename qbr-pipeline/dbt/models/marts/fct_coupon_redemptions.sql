{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key=['tenant_id', 'occurred_on', 'campaign_id', 'profile_segment']
) }}

-- Redemption rate is computed here from its components rather than stored as a
-- ratio, so the semantic layer can re-aggregate it at any grain without the
-- average-of-averages bug.
--
-- Source is int_coupon_events, a projection of the effects stream that already
-- carries the shopper segment. The previous version read a separate coupon feed
-- and joined lineage on coupon_code to recover the segment; coupon codes repeat,
-- so that join fanned rows out and inflated every count by roughly half.
with src as (
    select * from {{ ref('int_coupon_events') }}
    {% if is_incremental() %}
    where occurred_on >= (select coalesce(max(occurred_on), '1900-01-01') - interval 3 day from {{ this }})
    {% endif %}
)

select
    tenant                                              as tenant_id,
    occurred_on,
    campaign_id,
    profile_segment,
    count(*)                                            as redemption_attempts,
    sum(case when is_redeemed then 1 else 0 end)        as redemptions,
    sum(case when not is_redeemed then 1 else 0 end)    as rejections,
    count(distinct coupon_code)                         as distinct_coupons
from src
group by 1, 2, 3, 4
