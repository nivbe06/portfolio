"""Mock enrichment providers. Each seed file holds payloads shaped like the REAL
provider's API response (nested, provider-native keys). A per-provider normaliser
flattens that raw shape into our internal candidates - so the normalise step is real
integration work, not a pass-through. Swapping a mock for the live API means changing
only `_load` to an HTTP call; the normaliser stays."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .models import Candidate, SourceType

SEED_DIR = Path(__file__).parent / "seeds"

# Which internal fields each provider can answer (its specialisation).
PROVIDER_COVERAGE = {
    "clearbit":   {"industry", "employee_count", "annual_revenue_band", "country",
                   "ecommerce_platform", "funding_stage", "company_email"},
    "zoominfo":   {"employee_count", "country", "contact_email", "contact_phone",
                   "seniority_function", "linkedin_url", "company_email"},
    "apollo":     {"contact_email", "contact_phone", "seniority_function", "linkedin_url",
                   "company_email"},
    "crunchbase": {"industry", "annual_revenue_band", "funding_stage", "total_raised_usd"},
}

_cache: dict[str, dict] = {}


def _load(provider: str) -> dict:
    """Mock transport. A live client would issue the provider's HTTP request here and
    return the parsed JSON body unchanged; the normaliser below does the rest."""
    if provider not in _cache:
        path = SEED_DIR / f"{provider}.json"
        _cache[provider] = json.loads(path.read_text()) if path.exists() else {}
    return _cache[provider]


def _put(out: dict, field: str, value, conf: float, when: str) -> None:
    if value is not None and value != "" and value != []:
        out[field] = {"value": value, "confidence": conf, "observed_at": when}


# --- Per-provider normalisers: raw provider JSON -> {internal_field: {value,conf,when}} ---

def _norm_clearbit(raw: dict) -> dict:
    m = raw.get("meta", {})
    c, when = m.get("confidence", 0.6), m.get("fetchedAt", "")
    out: dict = {}
    _put(out, "industry", raw.get("category", {}).get("industry"), c, when)
    _put(out, "employee_count", raw.get("metrics", {}).get("employees"), c, when)
    _put(out, "annual_revenue_band", raw.get("metrics", {}).get("estimatedAnnualRevenue"), c, when)
    geo = raw.get("geo", {})
    _put(out, "country", geo.get("country") or geo.get("countryCode"), c, when)
    _put(out, "ecommerce_platform", raw.get("tech") or None, c, when)
    _put(out, "funding_stage", raw.get("fundingStage"), c, when)
    _put(out, "company_email", raw.get("site", {}).get("emailAddress"), c, when)
    return out


def _norm_person(raw: dict, phone_key: str, li_key: str) -> dict:
    m = raw.get("meta", {})
    c = m.get("matchConfidence", m.get("confidence", 0.6))
    when = m.get("lastUpdated") or m.get("updated_at", "")
    p = raw.get("person", {})
    out: dict = {}
    _put(out, "contact_email", p.get("email"), c, when)
    _put(out, "contact_phone", p.get(phone_key), c, when)
    _put(out, "seniority_function", p.get("jobTitle") or p.get("title"), c, when)
    _put(out, "linkedin_url", p.get(li_key), c, when)
    comp = raw.get("company", {})
    _put(out, "employee_count", comp.get("employeeCount"), c, when)
    _put(out, "country", comp.get("country"), c, when)
    _put(out, "company_email", comp.get("generalEmail"), c, when)
    return out


def _norm_zoominfo(raw: dict) -> dict:
    return _norm_person(raw, "directPhoneDialable", "linkedInUrl")


def _norm_apollo(raw: dict) -> dict:
    return _norm_person(raw, "sanitized_phone", "linkedin_url")


def _norm_crunchbase(raw: dict) -> dict:
    m = raw.get("meta", {})
    c, when = m.get("confidence", 0.6), m.get("as_of", "")
    org = raw.get("organization", {})
    out: dict = {}
    cats = org.get("categories") or []
    _put(out, "industry", cats[0] if cats else None, c, when)
    _put(out, "funding_stage", org.get("fundingStage"), c, when)
    _put(out, "total_raised_usd", org.get("fundingTotal", {}).get("valueUsd"), c, when)
    return out


NORMALISE: dict[str, Callable[[dict], dict]] = {
    "clearbit": _norm_clearbit,
    "zoominfo": _norm_zoominfo,
    "apollo": _norm_apollo,
    "crunchbase": _norm_crunchbase,
}


def fetch(provider: str, key: str, fields: list[str]) -> list[Candidate]:
    """Return candidates this provider has for the requested fields. Loads the raw
    provider-shaped payload, normalises it, then filters to coverage ∩ requested."""
    raw = _load(provider).get(key)
    if not raw:
        return []
    normalised = NORMALISE[provider](raw)
    coverage = PROVIDER_COVERAGE.get(provider, set())
    out: list[Candidate] = []
    for f in fields:
        if f in coverage and f in normalised:
            rec = normalised[f]
            out.append(Candidate(
                field=f, value=rec["value"], source=provider,
                source_type=SourceType.THIRD_PARTY,
                confidence=rec["confidence"], observed_at=rec["observed_at"]))
    return out
