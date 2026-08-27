from app.gates import (account_eligible, field_needs_enrichment, gate_b,
                       is_missing, resolve_company_key)
from app.models import Verdict


# --- is_missing ---

def test_is_missing_none():
    assert is_missing(None)


def test_is_missing_placeholder_string():
    assert is_missing("unknown")
    assert is_missing("  N/A  ")


def test_is_missing_empty_collections():
    assert is_missing([])
    assert is_missing({})


def test_is_missing_real_value_is_not_missing():
    assert not is_missing("Germany")
    assert not is_missing(0)  # 0 is a real (if unusual) value, not a placeholder


# --- account_eligible (Gate A, account level) ---

def test_account_eligible_business_domain():
    ok, reason = account_eligible({"domain": "acme-commerce.com"})
    assert ok and reason == ""


def test_account_eligible_company_name_only():
    ok, _ = account_eligible({"company_name": "ShopNord"})
    assert ok


def test_account_eligible_person_name_only():
    ok, _ = account_eligible({"contact_name": "Lars Nilsson"})
    assert ok


def test_account_eligible_free_email_alone_is_not_disqualifying():
    # A free personal email with no company/person name still has nothing to
    # resolve against -> ineligible. Free email alone never blocks eligibility
    # on its own; it just isn't a resolvable identifier by itself.
    ok, reason = account_eligible({"domain": "gmail.com"})
    assert not ok
    assert "no business domain" in reason


def test_account_eligible_free_email_with_company_name_is_eligible():
    ok, _ = account_eligible({"domain": "gmail.com", "company_name": "ShopNord"})
    assert ok


# --- resolve_company_key ---

def test_resolve_company_key_uses_input_domain_when_business():
    key, source, notes = resolve_company_key({"domain": "acme-commerce.com"})
    assert key == "acme-commerce.com"
    assert source == "input_domain"
    assert notes == []


def test_resolve_company_key_resolves_from_company_name():
    key, source, notes = resolve_company_key(
        {"domain": "gmail.com", "company_name": "Loyal Nordic"})
    assert key == "loyalnordic.se"
    assert source == "resolved_from_company_name"
    assert notes


def test_resolve_company_key_unresolvable_company_name():
    key, source, notes = resolve_company_key(
        {"domain": "gmail.com", "company_name": "Totally Unknown Co"})
    assert key is None
    assert source == "unresolved"


def test_resolve_company_key_nothing_to_go_on():
    key, source, notes = resolve_company_key({})
    assert key is None
    assert source == "unresolved"


# --- field_needs_enrichment (Gate A, field level) ---

def test_field_needs_enrichment_missing_value():
    assert field_needs_enrichment("industry", None)


def test_field_needs_enrichment_present_value_not_needed():
    assert not field_needs_enrichment("industry", "SaaS")


def test_field_needs_enrichment_free_email_is_harvested():
    # A personal email is present but not funnel-useful -> still needs enrichment
    assert field_needs_enrichment("contact_email", "lars@gmail.com")


def test_field_needs_enrichment_corp_email_is_satisfied():
    assert not field_needs_enrichment("contact_email", "lars@shopnord.de")


# --- gate_b (Gate B, value quality) ---

def test_gate_b_missing_value_is_recoverable():
    verdict, _ = gate_b("contact_email", None, {})
    assert verdict == Verdict.RECOVERABLE


def test_gate_b_invalid_email_format_is_recoverable():
    verdict, _ = gate_b("contact_email", "not-an-email", {})
    assert verdict == Verdict.RECOVERABLE


def test_gate_b_email_no_mx_is_recoverable():
    verdict, notes = gate_b("contact_email", "person@no-such-domain-xyz.example", {})
    assert verdict == Verdict.RECOVERABLE
    assert any("MX" in n for n in notes)


def test_gate_b_valid_phone_e164():
    verdict, _ = gate_b("contact_phone", "+491701234567", {})
    assert verdict == Verdict.PASS


def test_gate_b_invalid_phone_missing_country_code():
    verdict, notes = gate_b("contact_phone", "01701234567", {})
    assert verdict == Verdict.RECOVERABLE
    assert any("E.164" in n for n in notes)


def test_gate_b_employee_count_implausible_is_hard_fail():
    verdict, _ = gate_b("employee_count", -5, {})
    assert verdict == Verdict.HARD_FAIL


def test_gate_b_employee_count_non_numeric_is_hard_fail():
    verdict, _ = gate_b("employee_count", "lots", {})
    assert verdict == Verdict.HARD_FAIL


def test_gate_b_employee_count_valid():
    verdict, _ = gate_b("employee_count", 850, {})
    assert verdict == Verdict.PASS


def test_gate_b_country_known_token_passes():
    verdict, _ = gate_b("country", "Germany", {})
    assert verdict == Verdict.PASS


def test_gate_b_country_unknown_token_reconciles():
    verdict, _ = gate_b("country", "Atlantis", {})
    assert verdict == Verdict.RECONCILE


def test_gate_b_industry_unseeded_reconciles():
    verdict, _ = gate_b("industry", "Software", {})
    assert verdict == Verdict.RECONCILE


def test_gate_b_industry_already_canonical_passes():
    verdict, _ = gate_b("industry", "SaaS", {})
    assert verdict == Verdict.PASS


def test_gate_b_linkedin_url_valid():
    verdict, _ = gate_b("linkedin_url", "https://www.linkedin.com/in/jdoe/", {})
    assert verdict == Verdict.PASS


def test_gate_b_linkedin_url_invalid():
    verdict, _ = gate_b("linkedin_url", "https://example.com/jdoe", {})
    assert verdict == Verdict.RECOVERABLE
