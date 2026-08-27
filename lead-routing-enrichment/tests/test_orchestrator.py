from app.models import Method, SourceType, Verdict
from app.orchestrator import enrich_account


def test_gate_a_skips_account_with_nothing_to_enrich_against():
    res = enrich_account({"domain": "gmail.com"})
    assert res.skipped
    assert "no business domain" in res.skip_reason


def test_gate_a_skips_unresolvable_company_name():
    res = enrich_account({"domain": "gmail.com", "company_name": "Nobody Ever Heard Of This Inc"})
    assert res.skipped
    assert res.key_source == "unresolved" or res.skip_reason


def test_acme_commerce_clean_fill_from_real_seed_data():
    # Real fixture from app/seeds/demo_accounts.json: country is first-party and
    # present, so it must never trigger a provider call; the rest is missing.
    account = {
        "domain": "acme-commerce.com",
        "company_name": "Acme Commerce",
        "existing": {
            "country": "Germany",
            "industry": None,
            "employee_count": None,
            "ecommerce_platform": None,
        },
    }
    res = enrich_account(account, requested=["country", "industry", "employee_count",
                                             "ecommerce_platform"])
    assert not res.skipped
    assert "country" not in res.enriched  # already present, not in to_enrich

    industry = res.enriched["industry"]
    assert industry.value == "Ecommerce"
    assert industry.method == Method.DETERMINISTIC
    assert industry.source == "clearbit"

    employees = res.enriched["employee_count"]
    assert employees.value == 850
    assert employees.verdict == Verdict.PASS

    platform = res.enriched["ecommerce_platform"]
    assert platform.value == ["Shopify"]


def test_only_providers_owning_a_missing_field_are_called():
    account = {"domain": "acme-commerce.com", "existing": {"employee_count": None}}
    res = enrich_account(account, requested=["employee_count"])
    # employee_count's primary provider is clearbit (fields.py registry) - crunchbase
    # is never primary for it, so anti-fire-all must keep it out of the call list.
    assert res.providers_called == ["clearbit"]


def test_existing_value_is_kept_when_overwrite_finds_nothing_better():
    # Business domain resolves fine, but no provider has seed data for it -> the
    # waterfall exhausts with nothing usable, so the existing first-party value
    # must be kept rather than blanked.
    account = {
        "domain": "no-seed-data-for-this-domain.example",
        "existing": {"industry": "LegacyIndustry"},
    }
    res = enrich_account(account, requested=["industry"], overwrite=["industry"])
    assert not res.skipped
    industry = res.enriched["industry"]
    assert industry.value == "LegacyIndustry"
    assert industry.method == Method.UNCHANGED
    assert industry.source == "first_party"


def test_unrequested_field_present_is_left_alone():
    account = {
        "domain": "acme-commerce.com",
        "existing": {"country": "Germany", "industry": "SaaS"},
    }
    res = enrich_account(account, requested=["industry"])
    assert "industry" not in res.enriched  # already present, no overwrite requested


def test_llm_calls_are_counted_on_the_result():
    account = {
        "domain": "shopnord.de",
        "company_name": "ShopNord",
        "existing": {"industry": None},
    }
    res = enrich_account(account, requested=["industry"])
    # ShopNord's clearbit seed carries "Software", unseeded -> LLM stub path
    assert res.enriched["industry"].method == Method.LLM
    assert res.llm_calls == 1
