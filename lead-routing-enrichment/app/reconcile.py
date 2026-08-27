"""Reconciliation: translate a valid-but-foreign value into our canonical vocabulary.

Order per field: canonical DB (agreed terms + promoted aliases) -> already-canonical
check -> LLM proposal. The LLM only *proposes* a default now; it is NOT auto-cached.
A proposal becomes permanent only when db.PROMOTE_AT unique users confirm it (see
db.add_suggestion), so no single mistake goes global. Production value is 3; this demo
build sets it to 1 so a reviewer sees promotion in one pass - see db.py. Reference data
(countries, funding stages) is seeded into the canonical table at init."""
from __future__ import annotations

import json as _json
import os
import subprocess

from . import db
from . import fields as F
from .models import Method


def _load_api_key() -> str | None:
    """Resolve the Anthropic key: env var first, then the macOS keychain
    (`security find-generic-password -s ANTHROPIC_API_KEY`). Returns None if neither
    yields a key, in which case reconciliation falls back to the stub table."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if key:
        return key
    for flag in ("-s", "-a", "-l"):
        try:
            out = subprocess.run(
                ["security", "find-generic-password", "-w", flag, "ANTHROPIC_API_KEY"],
                capture_output=True, text=True, timeout=10)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (FileNotFoundError, subprocess.SubprocessError):
            return None
    return None


# Real Claude client. If no key is resolvable, reconciliation falls back to the stub
# table below, so the app still runs offline / without a key.
try:
    import anthropic
    _api_key = _load_api_key()
    _client = anthropic.Anthropic(api_key=_api_key) if _api_key else None
except Exception:
    _client = None

RECONCILE_MODEL = os.getenv("RECONCILE_MODEL", "claude-sonnet-5")
USE_REAL_LLM = os.getenv("USE_REAL_LLM", "1") != "0"

# Seed the canonical table from the known reference aliases (field -> {raw: canonical}).
_SEED_MAPS = {
    "industry": dict(F.INDUSTRY_SEED_ALIASES),
    "ecommerce_platform": dict(F.PLATFORM_ALIASES),
    "seniority_function": dict(F.SENIORITY_SEED),
    "funding_stage": dict(F.FUNDING_ALIASES),
    "country": dict(F.COUNTRY_MAP),
}

# Only categorical/vocabulary fields are reconciled. Numbers, emails, phones, URLs,
# and revenue bands are taken as-is - there is no "canonical term" to map them to.
RECONCILABLE = {"industry", "ecommerce_platform", "seniority_function",
                "country", "funding_stage"}

# Stand-in for an actual LLM call. Deterministic here so the demo repeats; the real
# system calls the model on a miss. Its output is a *proposal* shown to the user.
_LLM_TABLE = {
    "industry": {"software": "SaaS", "b2b saas": "SaaS", "b2b software": "SaaS",
                 "saas": "SaaS", "on-line shop": "Ecommerce", "webshop": "Ecommerce"},
    "ecommerce_platform": {"ct": "commercetools", "sf commerce": "Salesforce Commerce Cloud"},
    "seniority_function": {"director of growth": "growth_leader",
                           "chief technology officer": "eng_leader"},
}

llm_call_count = 0

db.init(_SEED_MAPS)


def reset_counters() -> None:
    global llm_call_count
    llm_call_count = 0


def reset_store() -> None:
    """Cold start: forget everything and reseed the canonical table."""
    global llm_call_count
    llm_call_count = 0
    db.reset()
    db.init(_SEED_MAPS)


def promoted_count() -> int:
    return db.promoted_count()


def _llm_reconcile(field: str, raw: str, allowed: set) -> tuple[str, float] | None:
    """Real Claude call: map a raw value to exactly one canonical term (or None).
    Returns (canonical, confidence) or None if the model declines / call fails."""
    if not (USE_REAL_LLM and _client and allowed):
        return None
    system = (
        "You are the reconciliation step in a CRM lead-enrichment pipeline. The end goal "
        "of the pipeline is to feed the CRM with clean, enriched contact data. You are "
        "only called after a value has already passed format validation and failed to "
        "match any seeded alias or previously-confirmed mapping - deterministic lookups "
        "ran first and missed. Your job is to normalise the raw value to exactly one "
        "canonical term from a fixed allowed list, so the CRM and downstream segmentation "
        "and campaign rules can match on it reliably.\n\n"
        "Your answer is a proposal, not a final decision: it is shown to a human reviewer "
        "and only becomes a permanent mapping after multiple independent users confirm "
        "the same result.\n\n"
        "Only pick a term if the raw value is genuinely that thing. If none of the "
        "allowed terms are a confident match, answer NONE - the raw value on its own "
        "is a fine result, no need to force a fit.\n\n"
        "Reply with ONLY a compact JSON object: "
        '{"canonical": "<one allowed term, or NONE if none fits>", "confidence": <0.0-1.0>}. '
        "No prose, no code fences."
    )
    user = (f"Field: {field}\nAllowed canonical terms: {sorted(allowed)}\n"
            f"Raw value: {raw!r}\nWhich canonical term does the raw value mean?")
    try:
        resp = _client.messages.create(
            model=RECONCILE_MODEL, max_tokens=256,
            system=system, messages=[{"role": "user", "content": user}],
        )
        text = next((b.text for b in resp.content if b.type == "text"), "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[4:] if text.lower().startswith("json") else text
        data = _json.loads(text)
        canon = data.get("canonical")
        if not canon or canon == "NONE" or canon not in allowed:
            return None
        return canon, float(data.get("confidence", 0.7))
    except Exception:
        return None


def _canonical_targets(field: str) -> set:
    return {
        "industry": F.VERTICALS,
        "ecommerce_platform": F.PLATFORM_VOCAB,
        "funding_stage": F.FUNDING_STAGES,
        "seniority_function": set(F.SENIORITY_SEED.values()),
        "country": set(F.COUNTRY_MAP.values()),
    }.get(field, set())


def reconcile(field: str, raw) -> tuple[object, Method, list[str], float | None]:
    """Return (canonical_value, method, notes, llm_confidence).
    llm_confidence is the model's own confidence in the mapping, and is None for any
    non-LLM (deterministic / unchanged) result."""
    global llm_call_count
    if raw is None:
        return raw, Method.UNCHANGED, [], None

    # non-categorical fields are not reconciled - taken as-is, no mapping note
    if field not in RECONCILABLE:
        return raw, Method.DETERMINISTIC, [], None

    if isinstance(raw, list):
        out, methods, notes, confs = [], set(), [], []
        for item in raw:
            v, m, n, c = reconcile(field, item)
            out.append(v); methods.add(m); notes += n
            if c is not None:
                confs.append(c)
        method = Method.LLM if Method.LLM in methods else Method.DETERMINISTIC
        return out, method, notes, (min(confs) if confs else None)

    key = str(raw).strip()
    lk = key.lower()

    # 1. canonical DB (seeded reference + user-promoted aliases)
    canon = db.get_canonical(field, key)
    if canon is not None:
        if canon.lower() == lk:
            return canon, Method.DETERMINISTIC, [], None
        return canon, Method.DETERMINISTIC, [f"canonical rule: {key} -> {canon}"], None

    # 2. already a canonical member?
    if key in _canonical_targets(field):
        return key, Method.DETERMINISTIC, [], None

    # 3. LLM proposal (real Claude call; not cached - a user must confirm it to make
    #    it permanent). Falls back to the stub table when offline / no API key.
    hit = _llm_reconcile(field, key, _canonical_targets(field))
    if hit is not None:
        llm_call_count += 1
        canon, conf = hit
        return canon, Method.LLM, [f"AI proposed {key} -> {canon}, confidence {conf:.2f} (unconfirmed)"], conf
    proposed = _LLM_TABLE.get(field, {}).get(lk)
    if proposed is not None:
        llm_call_count += 1
        return proposed, Method.LLM, [f"AI proposed {key} -> {proposed} (stub, unconfirmed)"], 0.80

    # 4. genuinely unknown -> leave raw, flag for review
    return key, Method.DETERMINISTIC, [f"no mapping for '{key}' -> review"], None
