-- The logic layer. Resolves session -> campaign -> ruleset -> effect and
-- attaches the shopper segment from the session to every effect it produced.
--
-- This model reduces nothing. That is deliberate: it is where joins and
-- business meaning live, so that the aggregation layers below it stay simple
-- enough to read and test. Format compaction happened in stg_, grain collapse
-- happens in fct_.
with sessions as (
    select
        session_id,
        tenant,
        application_id,
        profile_segment,
        evaluated_at,
        evaluated_on,
        cart_total,
        currency,
        state
    from {{ ref('stg_session_evaluations') }}
),

effects as (
    select * from {{ ref('stg_effects') }}
)

select
    e.event_id                      as effect_event_id,
    e.session_id,
    e.tenant,
    e.campaign_id,
    e.ruleset_id,
    e.effect_type,
    e.discount_value,
    e.points,
    e.is_monetary,
    e.coupon_code,
    e.fired_at,
    e.fired_on,
    s.application_id,
    -- Shopper segment travels from the session onto the effect. Without this,
    -- "the drop is concentrated in returning shoppers" is not answerable.
    s.profile_segment,
    s.cart_total                    as session_cart_total,
    s.currency                      as session_currency,
    s.state                         as session_state,
    s.session_id is not null        as has_parent_session
from effects e
left join sessions s
    on e.session_id = s.session_id
   and e.tenant = s.tenant
