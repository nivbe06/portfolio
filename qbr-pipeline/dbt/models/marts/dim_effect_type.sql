-- value_weight is what stops a notification spike outranking a discount
-- collapse in the salience ranker.
select
    effect_type,
    is_monetary,
    value_weight
from {{ ref('seed_effect_types') }}
