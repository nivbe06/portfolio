"""The two quality gates. Pure deterministic logic - no LLM here."""
from __future__ import annotations

import re
from typing import Any

from . import fields as F
from .models import Verdict


def is_missing(value: Any) -> bool:
    """Gate A field check: null, placeholder, or empty counts as missing."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in F.PLACEHOLDERS:
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def _is_business_domain(domain: str | None) -> bool:
    return bool(domain) and domain.lower() not in F.FREE_DOMAINS


def account_eligible(account: dict) -> tuple[bool, str]:
    """Gate A account check: is there ANY enrichable identifier?
    A free personal email is not disqualifying on its own - a company name or a
    person's name gives us something to resolve against."""
    domain = account.get("domain") or ""
    company = (account.get("company_name") or "").strip().lower()
    person = (account.get("contact_name") or "").strip()
    has_company = company not in ("", "unknown")
    if _is_business_domain(domain) or has_company or person:
        return True, ""
    return False, "no business domain, company, or person name to enrich against"


def resolve_company_key(account: dict) -> tuple[str | None, str, list[str]]:
    """Find the company domain to enrich against. Prefer a business domain on the
    record; otherwise resolve it from the company name (mock name-to-domain lookup)."""
    domain = account.get("domain") or ""
    if _is_business_domain(domain):
        return domain, "input_domain", []
    company = (account.get("company_name") or "").strip()
    if company and company.lower() not in ("", "unknown"):
        resolved = F.NAME_TO_DOMAIN.get(company.lower())
        if resolved:
            return resolved, "resolved_from_company_name", [
                f"company '{company}' -> {resolved} (name-to-domain)"]
        return None, "unresolved", [f"could not resolve a domain for '{company}'"]
    return None, "unresolved", ["no company domain and no resolvable company name"]


def field_needs_enrichment(field: str, value) -> bool:
    """Gate A field check. Missing, or present-but-not-funnel-useful (e.g. a personal
    email where we need the corporate one)."""
    if is_missing(value):
        return True
    if field == "contact_email":
        domain = str(value).split("@")[-1].lower()
        if domain in F.FREE_DOMAINS:
            return True   # harvest the corp email
    return False


# --- Gate B: field-specific quality checks ---

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_E164_RE = re.compile(r"^\+\d{8,15}$")
_LINKEDIN_RE = re.compile(r"^(https?://)?([\w-]+\.)?linkedin\.com/in/[\w\-]+/?(\?.*)?$", re.I)


def _mx_exists(email: str) -> bool:
    """Stub for a DNS MX lookup. Real system queries DNS; here we check a seeded set."""
    domain = email.split("@")[-1].lower()
    return domain in F.KNOWN_MX


def gate_b(field: str, value: Any, account: dict) -> tuple[Verdict, list[str]]:
    """Judge one enriched value. Returns (verdict, notes)."""
    notes: list[str] = []
    if is_missing(value):
        return Verdict.RECOVERABLE, ["provider returned no value"]

    if field in ("contact_email", "company_email"):
        if not _EMAIL_RE.match(str(value)):
            return Verdict.RECOVERABLE, ["not a valid email format"]
        if not _mx_exists(str(value)):
            return Verdict.RECOVERABLE, ["domain has no MX record (would bounce)"]
        return Verdict.PASS, ["RFC-valid + MX present"]

    if field == "contact_phone":
        if not _E164_RE.match(str(value)):
            return Verdict.RECOVERABLE, ["not E.164 (missing country code?)"]
        return Verdict.PASS, ["E.164 valid"]

    if field == "employee_count":
        try:
            n = int(value)
        except (TypeError, ValueError):
            return Verdict.HARD_FAIL, ["not numeric"]
        if n <= 0 or n > 5_000_000:
            return Verdict.HARD_FAIL, [f"implausible headcount ({n})"]
        return Verdict.PASS, []

    if field == "country":
        if str(value).strip().lower() not in F.COUNTRY_MAP:
            return Verdict.RECONCILE, ["unknown country token -> reconcile"]
        return Verdict.PASS, []

    if field == "industry":
        canon = _canon_industry_guess(value)
        if canon in F.VERTICALS:
            return Verdict.PASS, []
        return Verdict.RECONCILE, ["not in vertical taxonomy -> reconcile"]

    if field == "ecommerce_platform":
        raw = value if isinstance(value, list) else [value]
        if all(_canon_platform_guess(v) in F.PLATFORM_VOCAB for v in raw):
            return Verdict.PASS, []
        return Verdict.RECONCILE, ["platform alias -> reconcile"]

    if field == "seniority_function":
        if str(value).strip().lower() in F.SENIORITY_SEED:
            return Verdict.PASS, []
        return Verdict.RECONCILE, ["title not seeded -> reconcile"]

    if field == "linkedin_url":
        if _LINKEDIN_RE.match(str(value)):
            return Verdict.PASS, []
        return Verdict.RECOVERABLE, ["not a LinkedIn profile URL"]

    # fields with no special check (bands, funding, revenue) pass if present
    return Verdict.PASS, []


def _canon_industry_guess(v: Any) -> str:
    s = str(v).strip()
    if s in F.VERTICALS:
        return s
    return F.INDUSTRY_SEED_ALIASES.get(s.lower(), s)


def _canon_platform_guess(v: Any) -> str:
    s = str(v).strip()
    if s in F.PLATFORM_VOCAB:
        return s
    return F.PLATFORM_ALIASES.get(s.lower(), s)
