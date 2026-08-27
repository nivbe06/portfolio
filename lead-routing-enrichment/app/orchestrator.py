"""The pipeline: gate -> select -> fetch -> quality gate + waterfall -> reconcile -> assemble.
Every field carries how it was decided, so the UI can show LLM vs deterministic and route
low-confidence results to the human review queue."""
from __future__ import annotations

from . import fields as F
from . import providers as P
from . import reconcile as R
from . import selection as S
from .gates import (account_eligible, field_needs_enrichment, gate_b, is_missing,
                    resolve_company_key)
from .models import (AccountResult, Candidate, Method, ResolvedField, SourceType,
                     Verdict)

WATERFALL_CAP = 3   # max providers tried per field before giving up


def needed_fields(requested: list[str] | None) -> list[str]:
    if requested:
        return [f for f in requested if f in F.FIELD_REGISTRY]
    return [f for f, cfg in F.FIELD_REGISTRY.items() if cfg["needed"]]


def enrich_account(account: dict, requested: list[str] | None = None,
                    overwrite: list[str] | None = None) -> AccountResult:
    existing = account.get("existing", {})
    res = AccountResult(key=account.get("domain", ""))

    # --- Gate A: account eligibility ---
    ok, reason = account_eligible(account)
    if not ok:
        res.skipped = True
        res.skip_reason = reason
        res.needs_review = False
        return res

    # --- Resolve the company key (may come from the company name, not the email) ---
    key, key_source, knotes = resolve_company_key(account)
    if key is None:
        res.skipped = True
        res.skip_reason = knotes[0] if knotes else "no company domain resolvable"
        res.needs_review = False
        return res
    res.key = key
    res.key_source = key_source
    res.notes = knotes

    # --- Which fields to enrich ---
    # A selected field fills gaps by default. It only touches an existing value when
    # the caller explicitly opted that field into `overwrite` (the wizard's per-field
    # "also overwrite N existing" checkbox) - never implicitly. With no explicit
    # selection at all, fall back to missing-only.
    if requested is not None:
        overwrite_set = set(overwrite or [])
        to_enrich = [f for f in needed_fields(requested)
                     if field_needs_enrichment(f, existing.get(f)) or f in overwrite_set]
    else:
        to_enrich = [f for f in needed_fields(None)
                     if field_needs_enrichment(f, existing.get(f))]
    if not to_enrich:
        res.skip_reason = "all needed fields already present"
        return res

    # --- Selection: anti-fire-all. Only providers that own a field we're enriching ---
    plan = S.primary_plan(to_enrich)
    res.providers_called = list(plan.keys())

    for fld in to_enrich:
        rf = _enrich_one(fld, key, account, existing.get(fld))
        rf.before = existing.get(fld)
        res.enriched[fld] = rf

    res.providers_called = sorted({p for rf in res.enriched.values()
                                   for p in rf.providers_called})
    res.llm_calls = sum(1 for rf in res.enriched.values() if rf.method == Method.LLM)
    return res


def _enrich_one(field: str, key: str, account: dict, before=None) -> ResolvedField:
    tried: list[str] = []
    notes: list[str] = []
    chosen: Candidate | None = None
    verdict = Verdict.RECOVERABLE
    has_existing = before not in (None, "", []) and str(before).strip() != ""

    order = F.FIELD_REGISTRY[field]["providers"]
    for provider in order[:WATERFALL_CAP]:
        tried.append(provider)
        cands = P.fetch(provider, key, [field])
        if not cands:
            notes.append(f"{provider}: no data")
            continue
        cand = cands[0]
        verdict, vnotes = gate_b(field, cand.value, account)
        notes += [f"{provider}: {n}" for n in vnotes]
        if verdict in (Verdict.PASS, Verdict.RECONCILE):
            chosen = cand
            break
        if verdict == Verdict.HARD_FAIL:
            chosen = None
            break                       # implausible -> do not waterfall
        # RECOVERABLE -> waterfall to next provider

    if chosen is None:
        # Overwrite requested but nothing usable found: never lose an existing value -
        # keep it (first-party) rather than blanking the record.
        if has_existing:
            return ResolvedField(
                field=field, value=before, source="first_party",
                source_type=SourceType.FIRST_PARTY, method=Method.UNCHANGED,
                confidence=1.0, verdict=Verdict.PASS, raw_value=None,
                notes=notes + ["no newer value found - kept existing"],
                providers_called=tried)
        return ResolvedField(
            field=field, value=None, source="", source_type=SourceType.THIRD_PARTY,
            method=Method.UNCHANGED, confidence=0.0, verdict=verdict,
            raw_value=None, notes=notes + ["unresolved -> review queue"],
            providers_called=tried)

    # --- Reconcile the accepted value into our canonical vocabulary ---
    value, method, rnotes, llm_conf = R.reconcile(field, chosen.value)
    notes += rnotes
    # Keep BOTH signals distinct: the provider's match score stays the row confidence,
    # and the AI's mapping confidence is stored separately. The review gate (in api.py)
    # flags on the WEAKER of the two, so a confident mapping can't hide a weak match.
    llm_confidence = llm_conf if method == Method.LLM else None
    if has_existing and str(before).strip() != str(value).strip():
        notes.append(f"overwrote existing value {before!r}")
    return ResolvedField(
        field=field, value=value, source=chosen.source,
        source_type=chosen.source_type, method=method,
        confidence=chosen.confidence, verdict=Verdict.PASS,
        raw_value=chosen.value, llm_confidence=llm_confidence,
        observed_at=chosen.observed_at, notes=notes, providers_called=tried)
