-- Every effect the engine returns belongs to a session it was evaluated for.
-- An orphan means the lineage join in int_ is broken, which would silently
-- corrupt every per-segment number in the QBR, since shopper segment travels
-- from the session onto the effect.
select
    effect_event_id,
    session_id,
    tenant,
    'effect has no parent session' as failure_reason
from {{ ref('int_session_campaign_lineage') }}
where not has_parent_session
