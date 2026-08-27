-- Regression guard for a real bug.
--
-- fct_coupon_redemptions used to read a separate coupon feed and join
-- int_session_campaign_lineage on coupon_code to recover the shopper segment.
-- Coupon codes are not unique across effects, so that join multiplied rows:
-- acme-winback reported 66,648 redemption attempts against a true 44,560, and
-- every absolute coupon number in a QBR pack was roughly half again too big.
-- The rate survived because numerator and denominator inflated together, which
-- is exactly why it went unnoticed.
--
-- The fact is now built from int_coupon_events, which carries the segment
-- natively and needs no join. This asserts the totals still reconcile: one row
-- in, one row counted.
with fact_total as (
    select sum(redemption_attempts) as n from {{ ref('fct_coupon_redemptions') }}
),

source_total as (
    select count(*) as n
    from {{ ref('stg_effects') }}
    where effect_type in ('acceptCoupon', 'rejectCoupon')
)

select
    f.n as counted_in_fact,
    s.n as coupon_effects_in_source,
    'coupon fact does not reconcile with the effects it is built from' as failure_reason
from fact_total f
cross join source_total s
where f.n <> s.n
