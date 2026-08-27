"""FastAPI wrapper around the enrichment core. Thin by design: all logic lives in
the tested modules; this just exposes account-in -> enriched-out over HTTP and serves
the UI. In production the same core sits behind n8n."""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import db as DB
from . import providers as P
from . import reconcile as R
from . import selection as SEL
from .fields import FIELD_REGISTRY
from .gates import (account_eligible, field_needs_enrichment, gate_b,
                    resolve_company_key)
from .models import Method, Verdict
from .orchestrator import enrich_account, needed_fields

APP_DIR = Path(__file__).parent
SEED_DIR = APP_DIR / "seeds"
BATCHES = {"A": "demo_accounts.json", "B": "demo_accounts_b.json"}
QBR_DIR = APP_DIR.parent.parent / "task2" / "qbr" / "created-qbrs"
QBR_FILES = {
    "acme-commerce": "qbr-acme-commerce-2026-Q2.html",
    "brightline-grocers": "qbr-brightline-grocers-2026-Q2.html",
}

# Illustrative unit costs (replace with real contract rates). Provider API dominates;
# LLM is a rounding error. Used for the in-product cost estimate (Governor pattern).
PROVIDER_COST = {"clearbit": 0.20, "zoominfo": 0.50, "apollo": 0.40, "crunchbase": 0.10}
LLM_COST = 0.001
LOW_CONF = 0.75   # below this, flag the field for human attention

app = FastAPI(title="Lead Routing Enrichment")

# Column header -> internal field. Covers the common lead-list exports (Salesforce,
# HubSpot, Apollo, LinkedIn Sales Navigator) plus generic names. Headers matched
# case-insensitively; unknown columns are reported so the user can map them.
COLUMN_MAP = {
    "email": "email", "email address": "email", "work email": "email", "e-mail": "email",
    "company": "company_name", "company name": "company_name", "account name": "company_name",
    "organization": "company_name", "organization name": "company_name", "account": "company_name",
    "domain": "domain", "website": "domain", "company domain": "domain",
    "company domain name": "domain", "company website": "domain",
    "first name": "_first", "last name": "_last", "name": "contact_name", "full name": "contact_name",
    "title": "seniority_function", "job title": "seniority_function", "position": "seniority_function",
    "phone": "contact_phone", "phone number": "contact_phone", "direct phone": "contact_phone",
    "mobile": "contact_phone",
    "country": "country", "industry": "industry",
    "linkedin": "linkedin_url", "linkedin url": "linkedin_url", "person linkedin url": "linkedin_url",
}
# fields that live on the input record under "existing" (already-present values)
EXISTING_FIELDS = {"country", "industry", "contact_phone", "seniority_function", "linkedin_url"}
NEEDED_EXISTING = ["industry", "country", "employee_count", "ecommerce_platform",
                   "contact_email", "contact_phone", "seniority_function"]


# Demo batches are served as a CSV export, not as ready-made account objects, so the
# demo path goes through /api/ingest exactly like a pasted list. Headers below are the
# realistic CRM-export spellings that COLUMN_MAP already recognises.
EXISTING_CSV_HEADERS = {"country": "Country", "industry": "Industry",
                        "contact_phone": "Phone", "seniority_function": "Job Title",
                        "linkedin_url": "LinkedIn URL"}
# One column that deliberately maps to nothing, so the ingest summary demonstrates that
# unrecognised headers get reported rather than silently dropped.
UNMAPPED_COL = "Lead Source"
UNMAPPED_VALUES = ["Webinar", "Inbound", "Event", "Partner"]


def _accounts_to_csv(accounts: list[dict]) -> str:
    """Serialise demo accounts back to a CRM-style export.

    Only emits an existing-value column when some row actually carries one: an
    all-empty column is noise. contact_email is skipped because ingest derives it
    from Email, and employee_count / ecommerce_platform have no COLUMN_MAP entry,
    so they cannot survive a round trip (both are null on every demo row)."""
    used = [f for f in EXISTING_CSV_HEADERS
            if any((a.get("existing") or {}).get(f) for a in accounts)]
    headers = (["Company Name", "Company Domain Name", "Email", "First Name", "Last Name"]
               + [EXISTING_CSV_HEADERS[f] for f in used] + [UNMAPPED_COL])

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(headers)
    for i, a in enumerate(accounts):
        first, _, last = (a.get("contact_name") or "").partition(" ")
        row = [a.get("company_name") or "", a.get("domain") or "", a.get("email") or "",
               first, last]
        row += [(a.get("existing") or {}).get(f) or "" for f in used]
        row.append(UNMAPPED_VALUES[i % len(UNMAPPED_VALUES)])
        w.writerow(row)
    return buf.getvalue().strip()


def _domain_from(raw: str) -> str:
    raw = (raw or "").strip().lower()
    raw = re.sub(r"^https?://", "", raw)
    return raw.split("/")[0]


# Mock users (V1). Three standard operators share the same permissions; one admin
# adds term-promotion + audit review. Real multi-tenancy (SSO, per-org isolation) = V2.
USERS = {
    "ana":  {"name": "Ana Fischer", "role": "CSM",       "admin": False},
    "ben":  {"name": "Ben Novak",   "role": "SDR",       "admin": False},
    "cara": {"name": "Cara Weiß",   "role": "RevOps",    "admin": False},
    "dan":  {"name": "Dan Admin",   "role": "Admin",     "admin": True},
}
STANDARD_PERMS = ["enrich", "reject", "rerun", "crm_write"]
ADMIN_PERMS = STANDARD_PERMS + ["promote_terms", "review_audit"]

# In-memory audit trail + cost ledger (V1). Production = append-only tables.
AUDIT: list[dict] = []
COSTS: list[dict] = []


def _log(user: str, action: str, detail: str) -> None:
    from datetime import datetime, timezone
    AUDIT.append({
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "user": USERS.get(user, {}).get("name", user or "?"),
        "action": action, "detail": detail,
    })


class EnrichRequest(BaseModel):
    batch: str | None = None
    accounts: list[dict] | None = None
    limit: int | None = None      # enrich only the first N (Sample Response pattern)
    fields: list[str] | None = None    # which fields to enrich (default = stakeholder set)
    overwrite_fields: list[str] = []   # subset of `fields` allowed to touch existing values
    user: str = "ana"


class IngestRequest(BaseModel):
    csv_text: str


class LogRequest(BaseModel):
    user: str = "ana"
    action: str
    detail: str = ""


def _field_row(name: str, rf) -> dict:
    # gate on the WEAKER of provider-match and AI-mapping confidence (Hagara #1)
    effective = min(rf.confidence, rf.llm_confidence) if rf.llm_confidence is not None else rf.confidence
    return {
        "field": name,
        "before": rf.before,
        "raw": rf.raw_value,
        "value": rf.value,
        "method": rf.method.value,
        "verdict": rf.verdict.value,
        "source": rf.source,
        "confidence": round(rf.confidence, 2),
        "llm_confidence": round(rf.llm_confidence, 2) if rf.llm_confidence is not None else None,
        "low_conf": rf.value is not None and effective < LOW_CONF,
        "observed_at": rf.observed_at,
        "providers_called": rf.providers_called,
        "notes": rf.notes,
        "kept": False,
    }


def _account_cost(providers_called: list[str], llm_calls: int) -> float:
    return round(sum(PROVIDER_COST.get(p, 0.0) for p in providers_called)
                 + llm_calls * LLM_COST, 3)


def _field_costs(res) -> dict[str, float]:
    """Provider cost is billed once per provider per account (see _account_cost's
    dedup), not per field, so split it evenly across the fields that provider
    actually resolved here. LLM cost is already per-field."""
    counts: dict[str, int] = {}
    for rf in res.enriched.values():
        if rf.method != Method.UNCHANGED and rf.source in PROVIDER_COST:
            counts[rf.source] = counts.get(rf.source, 0) + 1
    out = {}
    for f, rf in res.enriched.items():
        c = 0.0
        if rf.method != Method.UNCHANGED and rf.source in PROVIDER_COST:
            c += PROVIDER_COST[rf.source] / counts[rf.source]
        if rf.method == Method.LLM:
            c += LLM_COST
        out[f] = round(c, 4)
    return out


def _serialize(account: dict, res) -> dict:
    label = account.get("domain") or account.get("email") or "?"
    out = {
        "company": account.get("company_name", "?"),
        "label": label,
        "skipped": res.skipped,
        "skip_reason": res.skip_reason,
        "key": res.key,
        "key_source": res.key_source,
        "providers_called": res.providers_called,
        "llm_calls": res.llm_calls,
        "needs_review": res.needs_review,
        "cost": _account_cost(res.providers_called, res.llm_calls),
        "low_conf_count": 0,
        "fields": [],
    }
    if res.skipped:
        return out

    existing = account.get("existing", {})
    kept = [f for f in needed_fields(None)
            if f not in res.enriched and not field_needs_enrichment(f, existing.get(f))]
    for f in kept:
        out["fields"].append({
            "field": f, "before": existing.get(f), "raw": existing.get(f),
            "value": existing.get(f), "method": "unchanged", "verdict": "kept",
            "source": "first_party", "confidence": 1.0, "llm_confidence": None,
            "low_conf": False, "observed_at": "", "providers_called": [],
            "notes": [], "kept": True,
        })
    for f, rf in res.enriched.items():
        out["fields"].append(_field_row(f, rf))
    out["low_conf_count"] = sum(1 for r in out["fields"] if r.get("low_conf"))
    return out


@app.get("/")
def index() -> FileResponse:
    return FileResponse(APP_DIR / "web" / "index.html")


@app.get("/deck")
def deck() -> FileResponse:
    return FileResponse(APP_DIR / "web" / "deck.html")


@app.get("/home")
def home() -> FileResponse:
    return FileResponse(APP_DIR / "web" / "home.html")


@app.get("/qbr/{slug}")
def qbr(slug: str) -> FileResponse:
    filename = QBR_FILES.get(slug)
    if not filename:
        raise HTTPException(404, "no QBR for that slug")
    return FileResponse(QBR_DIR / filename)


@app.get("/api/state")
def state() -> dict:
    return {"cached_aliases": R.promoted_count()}


@app.get("/api/users")
def users() -> dict:
    return {"users": [{"id": k, **v,
                       "perms": ADMIN_PERMS if v["admin"] else STANDARD_PERMS}
                      for k, v in USERS.items()]}


@app.get("/api/terms")
def terms() -> dict:
    """The canonical terminology map, visible to everyone."""
    return {"terms": DB.list_canonical(), "promoted": DB.promoted_count()}


class PlanRequest(BaseModel):
    accounts: list[dict] = []
    fields: list[str] | None = None
    overwrite_fields: list[str] = []


@app.post("/api/plan")
def plan(req: PlanRequest) -> dict:
    """Scope preview (#8 scope-before-spend): how many provider lookups a run will make,
    without enriching anything or spending. Shown as effort, not money."""
    requested = req.fields or [f for f, c in FIELD_REGISTRY.items() if c["needed"]]
    overwrite_set = set(req.overwrite_fields)
    lookups, eligible, skipped = 0, 0, []
    for acc in req.accounts:
        name = acc.get("company_name") or acc.get("domain") or acc.get("email") or "?"
        ok, reason = account_eligible(acc)
        key, _src, notes = resolve_company_key(acc) if ok else (None, "", [])
        if not key:
            skipped.append({"name": name, "reason": reason or (notes[0] if notes else "no company key")})
            continue
        eligible += 1
        existing = acc.get("existing", {})
        to_run = [f for f in requested
                  if field_needs_enrichment(f, existing.get(f)) or f in overwrite_set]
        lookups += len(SEL.primary_plan(to_run))
    return {"lookups": lookups, "accounts": eligible, "skipped": len(skipped),
            "skipped_accounts": skipped, "fields": len(requested)}


@app.get("/api/costs")
def costs(user: str = "ana") -> dict:
    """Admin cost dashboard (#6). Non-admins get nothing but their own total."""
    is_admin = USERS.get(user, {}).get("admin", False)
    total = round(sum(c["cost"] for c in COSTS), 2)
    by_user: dict[str, float] = {}
    by_provider: dict[str, float] = {}
    for c in COSTS:
        by_user[c["user"]] = round(by_user.get(c["user"], 0) + c["cost"], 2)
        for p, n in c["providers"].items():
            by_provider[p] = round(by_provider.get(p, 0) + n * PROVIDER_COST.get(p, 0), 2)
    if not is_admin:
        me = USERS.get(user, {}).get("name")
        return {"is_admin": False, "my_total": by_user.get(me, 0.0)}
    # AI (LLM) is the remainder so provider lines + AI reconcile to the total exactly
    ai_cost = round(total - sum(by_provider.values()), 2)
    return {"is_admin": True, "total": total, "runs": len(COSTS),
            "by_user": by_user, "by_provider": by_provider, "ai_cost": ai_cost}


@app.get("/api/enrichment-log")
def enrichment_log(user: str = "ana", company: str | None = None, field: str | None = None,
                    run_id: str | None = None, limit: int = 500) -> dict:
    """Admin-only field-resolution audit trail (#9). Same admin gate as costs/audit."""
    is_admin = USERS.get(user, {}).get("admin", False)
    if not is_admin:
        return {"is_admin": False, "rows": []}
    return {"is_admin": True, "rows": DB.list_enrichment_log(company, field, run_id, limit)}


@app.get("/api/field-stats")
def field_stats() -> dict:
    return {"stats": DB.list_field_stats()}


@app.get("/api/demo/{batch}")
def demo(batch: str) -> dict:
    """Demo input accounts for the wizard's 'Load demo data' affordance."""
    if batch not in BATCHES:
        return {"accounts": [], "csv": ""}
    accounts = json.loads((SEED_DIR / BATCHES[batch]).read_text())
    return {"accounts": accounts, "csv": _accounts_to_csv(accounts)}


@app.get("/api/fields")
def fields() -> dict:
    """The field catalogue. `default` = the stakeholder-agreed funnel set enriched
    automatically; the rest are opt-in per run."""
    return {"fields": [{"field": f, "level": cfg["level"], "default": cfg["needed"]}
                       for f, cfg in FIELD_REGISTRY.items()]}


@app.get("/api/audit")
def audit(user: str = "ana") -> dict:
    # only admins review the full trail; others see their own actions
    is_admin = USERS.get(user, {}).get("admin", False)
    rows = AUDIT if is_admin else [a for a in AUDIT if a["user"] == USERS.get(user, {}).get("name")]
    return {"audit": list(reversed(rows[-50:])), "is_admin": is_admin}


@app.post("/api/log")
def log(req: LogRequest) -> dict:
    _log(req.user, req.action, req.detail)
    return {"ok": True}


class SuggestItem(BaseModel):
    field: str
    reconcile_from: str
    reconcile_to: str


class SuggestRequest(BaseModel):
    user: str = "ana"
    items: list[SuggestItem] = []


@app.post("/api/suggest")
def suggest(req: SuggestRequest) -> dict:
    """Called on CRM write: store each field's reconciliation as a user suggestion.
    A from->to mapping confirmed by DB.PROMOTE_AT unique users is promoted to canonical
    (set to 1 for this demo build - see db.py for the production value of 3)."""
    promotions = []
    for it in req.items:
        r = DB.add_suggestion(it.field, it.reconcile_from, it.reconcile_to, req.user)
        if r["promoted"]:
            promotions.append(f"{it.reconcile_from} -> {it.reconcile_to}")
            _log(req.user, "promote_term", f"{it.field}: {it.reconcile_from} -> {it.reconcile_to} ({r['unique_users']}/{r['threshold']} users)")
    return {"promotions": promotions, "promoted_count": DB.promoted_count()}


class RefetchRequest(BaseModel):
    account: dict
    field: str
    user: str = "ana"


@app.post("/api/refetch")
def refetch(req: RefetchRequest) -> dict:
    """#8: for a dropped/low-quality field, search ALL providers that cover it (no
    waterfall cap, ignore the primary's hard-fail) and take the first that passes."""
    field, key = req.field, req.account.get("domain") or req.account.get("key", "")
    tried, notes = [], []
    for provider in FIELD_REGISTRY.get(field, {}).get("providers", []):
        tried.append(provider)
        cands = P.fetch(provider, key, [field])
        if not cands:
            notes.append(f"{provider}: no data"); continue
        cand = cands[0]
        verdict, vnotes = gate_b(field, cand.value, req.account)
        notes += [f"{provider}: {n}" for n in vnotes]
        if verdict in (Verdict.PASS, Verdict.RECONCILE):
            value, method, rnotes, llm_conf = R.reconcile(field, cand.value)
            ai_conf = llm_conf if method == Method.LLM else None
            effective = min(cand.confidence, ai_conf) if ai_conf is not None else cand.confidence
            _log(req.user, "refetch", f"{field} found via {provider}")
            return {"found": True, "field": field, "raw": cand.value, "value": value,
                    "method": method.value, "verdict": "pass", "source": provider,
                    "confidence": round(cand.confidence, 2),
                    "llm_confidence": round(ai_conf, 2) if ai_conf is not None else None,
                    "low_conf": effective < LOW_CONF,
                    "observed_at": cand.observed_at, "providers_called": tried,
                    "notes": notes + rnotes, "kept": False}
    _log(req.user, "refetch", f"{field}: no source had a usable value")
    return {"found": False, "field": field, "notes": notes, "providers_called": tried}


@app.post("/api/reset")
def reset() -> dict:
    R.reset_store()
    return {"ok": True, "cached_aliases": R.promoted_count()}


@app.post("/api/ingest")
def ingest(req: IngestRequest) -> dict:
    """Parse a pasted/dropped CSV into account objects. Auto-maps known columns;
    reports unmapped headers and rows with no usable identifier."""
    text = req.csv_text.strip()
    if not text:
        return {"accounts": [], "mapping": {}, "unmapped": [], "dropped": 0, "error": "empty input"}
    # sniff delimiter (comma / tab / semicolon)
    try:
        dialect = csv.Sniffer().sniff(text.splitlines()[0] + "\n" + (text.splitlines()[1] if len(text.splitlines()) > 1 else ""), delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = reader.fieldnames or []

    mapping = {h: COLUMN_MAP.get((h or "").strip().lower()) for h in headers}
    unmapped = [h for h, f in mapping.items() if f is None]

    accounts, dropped = [], 0
    for row in reader:
        acc = {"domain": "", "company_name": "", "email": "", "contact_name": "",
               "existing": {f: None for f in NEEDED_EXISTING}}
        first = last = ""
        for h, val in row.items():
            field = mapping.get(h)
            v = (val or "").strip()
            if not field or not v:
                continue
            if field == "domain":
                acc["domain"] = _domain_from(v)
            elif field == "email":
                acc["email"] = v
                acc["existing"]["contact_email"] = v
            elif field == "company_name":
                acc["company_name"] = v
            elif field == "contact_name":
                acc["contact_name"] = v
            elif field == "_first":
                first = v
            elif field == "_last":
                last = v
            elif field in EXISTING_FIELDS:
                acc["existing"][field] = v
        if not acc["contact_name"] and (first or last):
            acc["contact_name"] = (first + " " + last).strip()
        # need at least one identifier, else Gate A would skip anyway
        if not (acc["domain"] or acc["company_name"] or acc["email"]):
            dropped += 1
            continue
        accounts.append(acc)

    return {
        "accounts": accounts,
        "mapping": {h: f for h, f in mapping.items() if f and not f.startswith("_")},
        "unmapped": unmapped,
        "dropped": dropped,
        "count": len(accounts),
    }


@app.post("/api/enrich")
def enrich(req: EnrichRequest) -> dict:
    if req.batch:
        if req.batch not in BATCHES:
            raise HTTPException(
                status_code=400,
                detail=f"unknown batch '{req.batch}'; expected one of {sorted(BATCHES)}",
            )
        accounts = json.loads((SEED_DIR / BATCHES[req.batch]).read_text())
    else:
        accounts = req.accounts or []
    total_in_batch = len(accounts)
    if req.limit:
        accounts = accounts[: req.limit]

    R.reset_counters()
    cached_before = R.promoted_count()
    account_results = [enrich_account(a, req.fields, req.overwrite_fields) for a in accounts]
    results = [_serialize(a, res) for a, res in zip(accounts, account_results)]

    # log the run: who, how many, and which non-default fields were requested
    default_set = {f for f, c in FIELD_REGISTRY.items() if c["needed"]}
    requested = set(req.fields or default_set)
    extra = sorted(requested - default_set)
    _log(req.user, "enrich",
         f"{len(accounts)} account(s)"
         + (f", +custom fields: {', '.join(extra)}" if extra else ", default fields")
         + f", ${round(sum(r['cost'] for r in results), 2)}")

    # #3 field-enrichment stats + #6 cost ledger
    for r in results:
        if r["skipped"]:
            continue
        for f in r["fields"]:
            if f["kept"]:
                continue
            existed = f["before"] not in (None, "", []) and str(f["before"]).strip() != ""
            DB.record_field_enrichment(f["field"], f["field"] in default_set,
                                       existed, f["value"] is not None, req.user)
    prov_counts: dict[str, int] = {}
    for r in results:
        for p in r["providers_called"]:
            prov_counts[p] = prov_counts.get(p, 0) + 1
    from datetime import datetime, timezone
    import uuid
    run_id = uuid.uuid4().hex[:12]
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    COSTS.append({"user": USERS.get(req.user, {}).get("name", req.user),
                  "cost": round(sum(r["cost"] for r in results), 3),
                  "providers": prov_counts,
                  "ts": run_ts})

    # Enrichment log (#9): one row per field resolution, for audit/debugging.
    log_rows = []
    for acc, res, r in zip(accounts, account_results, results):
        if r["skipped"]:
            continue
        field_costs = _field_costs(res)
        for f in r["fields"]:
            is_successful = f["value"] is not None and f["verdict"] in ("pass", "reconcile", "kept")
            log_rows.append({
                "run_id": run_id, "ts": run_ts, "user": req.user,
                "company": r["company"], "account_key": res.key, "field": f["field"],
                "service": f["source"] or "",
                "before_value": json.dumps(f["before"], default=str),
                "after_value": json.dumps(f["value"], default=str),
                "confidence": f["confidence"],
                "is_successful": 1 if is_successful else 0,
                "cost": 0.0 if f["kept"] else field_costs.get(f["field"], 0.0),
                "observed_at": f["observed_at"],
            })
    DB.record_enrichment_log(log_rows)

    return {
        "results": results,
        "summary": {
            "accounts": len(accounts),
            "batch_total": total_in_batch,
            "extra_fields": extra,
            "is_sample": bool(req.limit) and req.limit < total_in_batch,
            "enriched": sum(1 for r in results if not r["skipped"]),
            "skipped": sum(1 for r in results if r["skipped"]),
            "provider_calls": sum(len(r["providers_called"]) for r in results),
            "llm_calls": R.llm_call_count,
            "cost": round(sum(r["cost"] for r in results), 2),
            "low_conf_total": sum(r["low_conf_count"] for r in results),
            "cached_before": cached_before,
            "cached_after": R.promoted_count(),
        },
    }
