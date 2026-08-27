from app import reconcile as R
from app.models import Method


def test_non_categorical_field_passes_through_unchanged():
    value, method, notes, conf = R.reconcile("employee_count", 850)
    assert value == 850
    assert method == Method.DETERMINISTIC
    assert notes == []
    assert conf is None


def test_none_value_is_unchanged():
    value, method, notes, conf = R.reconcile("industry", None)
    assert value is None
    assert method == Method.UNCHANGED


def test_seeded_alias_reconciles_deterministically():
    value, method, notes, conf = R.reconcile("industry", "e-commerce")
    assert value == "Ecommerce"
    assert method == Method.DETERMINISTIC


def test_already_canonical_value_passes_through():
    value, method, _, _ = R.reconcile("industry", "SaaS")
    assert value == "SaaS"
    assert method == Method.DETERMINISTIC


def test_unseeded_value_falls_to_llm_stub_when_offline():
    # conftest forces R._client = None, so this exercises the offline stub table,
    # not a real network call.
    value, method, notes, conf = R.reconcile("industry", "Software")
    assert value == "SaaS"
    assert method == Method.LLM
    assert conf == 0.80
    assert R.llm_call_count == 1


def test_genuinely_unknown_value_is_left_raw_and_flagged():
    value, method, notes, _ = R.reconcile("industry", "Underwater Basket Weaving")
    assert value == "Underwater Basket Weaving"
    assert method == Method.DETERMINISTIC
    assert any("review" in n for n in notes)


def test_llm_proposal_is_not_auto_cached():
    R.reconcile("industry", "Software")
    assert R.promoted_count() == 0
    # asking again still costs an LLM call - nothing was cached from the proposal alone
    R.reconcile("industry", "Software")
    assert R.llm_call_count == 2


def test_list_value_reconciles_each_item():
    value, method, _, _ = R.reconcile("ecommerce_platform", ["shopify", "sfcc"])
    assert value == ["Shopify", "Salesforce Commerce Cloud"]
    assert method == Method.DETERMINISTIC


def test_reset_store_clears_llm_counter_and_canonical_learning():
    R.reconcile("industry", "Software")
    assert R.llm_call_count == 1
    R.reset_store()
    assert R.llm_call_count == 0
    # after reset, "Software" is unseeded again -> costs another LLM call
    R.reconcile("industry", "Software")
    assert R.llm_call_count == 1
