from app.selection import fallbacks_for, primary_plan


def test_primary_plan_maps_field_to_primary_provider():
    plan = primary_plan(["industry"])
    assert plan == {"clearbit": ["industry"]}


def test_primary_plan_groups_fields_by_shared_primary():
    plan = primary_plan(["industry", "employee_count"])
    assert plan == {"clearbit": ["industry", "employee_count"]}


def test_primary_plan_never_calls_a_provider_with_no_needed_field():
    # crunchbase is not primary for any commonly-missing contact field, so a
    # plan built only from contact fields must never mention it (anti-fire-all).
    plan = primary_plan(["contact_email", "contact_phone"])
    assert "crunchbase" not in plan


def test_primary_plan_empty_input_yields_empty_plan():
    assert primary_plan([]) == {}


def test_fallbacks_for_excludes_already_tried():
    fallbacks = fallbacks_for("employee_count", ["clearbit"])
    assert "clearbit" not in fallbacks


def test_fallbacks_for_preserves_registry_order():
    from app import fields as F
    order = F.FIELD_REGISTRY["employee_count"]["providers"]
    assert fallbacks_for("employee_count", []) == order
