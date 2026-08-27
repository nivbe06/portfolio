-- Coupon lifecycle, projected out of the effects stream.
--
-- Talon.One has no coupon export. A coupon's outcome *is* an effect:
-- acceptCoupon and rejectCoupon (and couponCreated / reserveCoupon /
-- rollbackCoupon, which this dataset does not emit). Reading a parallel coupon
-- feed modelled the mock generator's convenience rather than the platform, so
-- the feed is gone and this projection replaces it.
--
-- Projecting from the lineage model rather than from stg_effects directly is
-- what removes the old bug: fct_coupon_redemptions used to join a coupon feed
-- back to lineage on coupon_code to recover the shopper segment, and coupon
-- codes are not unique (115,924 coupon effects over 84,317 codes), so every
-- count fanned out by ~1.5x. Here the segment is already on the row.
select
    effect_event_id                     as event_id,
    session_id,
    tenant,
    campaign_id,
    coupon_code,
    effect_type,
    profile_segment,
    fired_at                            as occurred_at,
    fired_on                            as occurred_on,
    effect_type = 'acceptCoupon'        as is_redeemed
from {{ ref('int_session_campaign_lineage') }}
where effect_type in ('acceptCoupon', 'rejectCoupon')
