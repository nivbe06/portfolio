{% test expression_is_true(model, expression) %}
{#-
    Minimal stand-in for dbt_utils.expression_is_true.

    Hand-rolled rather than pulling dbt_utils in for one macro: the package adds
    a dependency, a lockfile and a version-compatibility surface, and this is
    four lines. Fails on any row where the expression is not true.
-#}
select *
from {{ model }}
where not ({{ expression }})
{% endtest %}
