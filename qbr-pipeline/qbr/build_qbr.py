"""Build a QBR pack, on demand, in two phases.

The pipeline is split so that the agent asking for the QBR is the one that writes
its prose. There is no model call anywhere in this file, and nothing here reads a
credential.

  Phase 1  --emit-payloads
    Fetch account context, run the bundle queries against the tenant-scoped
    semantic layer, rank anomalies by materiality, and write one JSON file
    containing each section's data alongside the writing rules from its bundle.
    Everything in this phase is deterministic.

  (the caller writes the prose)

  Phase 2  --with-narratives <file>
    Read the prose back, check every figure in it against the payload that
    produced it, render the charts and the HTML. Exits non-zero and names the
    offending figures if any section fails, so the caller can rewrite and retry.

Splitting it this way is not a convenience. It puts the grounding check on the
other side of a process boundary from whatever wrote the text, so the control
holds regardless of which model, agent or human produced the prose.

Usage:
    python3 qbr/build_qbr.py --tenant acme-commerce --quarter 2026-Q2 --emit-payloads
    python3 qbr/build_qbr.py --tenant acme-commerce --quarter 2026-Q2 \
        --with-narratives out/narratives-acme-commerce-2026-Q2.json

Normally you do not run these by hand. `/create-qbr` runs both halves and writes
the prose in between.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml

import charts
import cube_client
import grounding
import render
import retrieval
import salience

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLE_DIR = os.path.join(HERE, "bundles")
OUT_DIR = os.path.join(HERE, "created-qbrs")


def load_registry() -> dict:
    with open(os.path.join(BUNDLE_DIR, "_registry.yml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_bundle(bundle_id: str) -> dict:
    with open(os.path.join(BUNDLE_DIR, f"{bundle_id}.yml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def prior_quarter(quarter: str) -> str:
    year, q = quarter.split("-Q")
    year, q = int(year), int(q)
    return f"{year - 1}-Q4" if q == 1 else f"{year}-Q{q - 1}"


def fetch_context(tenant: str, quarter: str) -> dict[str, Any]:
    """Account facts, straight from the semantic layer."""
    rows = cube_client.run_query({
        "measures": [
            "qbr_overview.sessions_evaluated",
            "qbr_overview.cart_value",
            "qbr_overview.sessions_qoq",
            "qbr_overview.api_error_rate",
            "qbr_overview.net_points_outstanding",
        ],
        "dimensions": [
            "qbr_overview.tenant_name", "qbr_overview.plan_tier",
            "qbr_overview.country", "qbr_overview.currency",
            "qbr_overview.has_loyalty_entitlement",
        ],
        "filters": [{
            "member": "qbr_overview.quarter_label",
            "operator": "equals", "values": [quarter],
        }],
        "limit": 5,
    }, tenant)

    if not rows:
        raise SystemExit(f"No data for {tenant} in {quarter}.")

    row = rows[0]
    return {
        "tenant_id": tenant,
        "tenant_name": row.get("tenant_name", tenant),
        "plan_tier": row.get("plan_tier", ""),
        "country": row.get("country", ""),
        "currency": row.get("currency", ""),
        "quarter": quarter,
        "prior_quarter": prior_quarter(quarter),
        "has_loyalty": row.get("has_loyalty_entitlement"),
        "sessions_evaluated": row.get("sessions_evaluated"),
        "cart_value": row.get("cart_value"),
        "sessions_qoq": row.get("sessions_qoq"),
        "api_error_rate": row.get("api_error_rate"),
        "net_points_outstanding": row.get("net_points_outstanding"),
    }


def _run(spec_key: str, bundle: dict, params: dict, tenant: str) -> list[dict]:
    spec = bundle.get(spec_key)
    if not spec:
        return []
    return cube_client.run_query(cube_client.build_query(spec, params), tenant)


def gather_section(bundle_id: str, context: dict, tenant: str) -> dict[str, Any]:
    """Everything for one section except its prose."""
    bundle = load_bundle(bundle_id)
    params = {"quarter": context["quarter"], "prior_quarter": context["prior_quarter"]}

    rows = _run("query", bundle, params, tenant)
    breakdown = _run("breakdown", bundle, params, tenant)
    trend = _run("trend", bundle, params, tenant)

    payload: dict[str, Any] = {"rows": rows}
    if breakdown:
        payload["segment_breakdown"] = breakdown

    ranking: dict[str, Any] = {}
    if bundle_id == "anomalies":
        ranking = salience.rank(rows)
        payload = {
            "ranked_movements": ranking["ranked"],
            "candidates_considered": ranking["candidate_count"],
            "deliberately_suppressed": [
                {
                    "entity_label": r.get("entity_label"),
                    "metric_name": r.get("metric_name"),
                    "z_score": r.get("z_score"),
                    "salience": r.get("salience"),
                    "why": r.get("salience_reasons"),
                }
                for r in ranking["suppressed"]
            ],
        }

    # The qualitative half. Declared in the bundle manifest rather than keyed off
    # the section id, so adding context to a section is a manifest edit and not a
    # code change - the same reason the queries live in the manifests.
    context_spec = bundle.get("context") or {}
    evidence: list[dict[str, Any]] = []

    if context_spec.get("evidence_for_movements"):
        evidence = retrieval.retrieve_for_movements(
            tenant,
            ranking.get("ranked", []),
            per_movement=int(context_spec.get("per_movement", 1)),
        )
        payload["evidence"] = evidence

    if context_spec.get("commitments"):
        payload["commitments"] = retrieval.retrieve_commitments(tenant)

    if context_spec:
        payload["context_corpus"] = retrieval.corpus_summary(tenant)
        # Written into the payload rather than left implicit. The model is being
        # handed free text for the first time, and the boundary has to travel
        # with the data it applies to.
        payload["context_rules"] = [
            "Context explains a movement. It is never the source of a figure.",
            "Cite evidence by its citation_id in square brackets, for example [C1].",
            "Quote only what a snippet says, character for character. Paraphrase otherwise.",
            "Do not cite a citation_id that is not in this payload.",
        ]

    return {
        "id": bundle_id,
        "title": bundle["title"],
        "payload": payload,
        "writing_rules": bundle.get("narrative", {}),
        "rows": rows,
        "trend": trend,
        "breakdown": breakdown,
        "ranking": ranking,
        "evidence": evidence,
    }


def _figures(bundle: dict, rows: list[dict], trend: list[dict],
             breakdown: list[dict], ranking: dict) -> list[str]:
    out: list[str] = []
    for chart in bundle.get("charts", []):
        source = {
            "query": rows, "trend": trend, "breakdown": breakdown,
            "ranked": ranking.get("ranked", []),
        }.get(chart.get("source", "query"), rows)

        kind = chart["type"]
        if kind == "grouped_bar":
            out.append(charts.grouped_bar(
                source, chart["series"], chart["by"], chart["title"],
                chart.get("format", "number")))
        elif kind == "line":
            out.append(charts.line(
                source, chart["metric"], chart["by"], chart.get("group"),
                chart["title"], chart.get("format", "number")))
        elif kind in ("state_table", "salience_table"):
            out.append(charts.table(
                source, chart["columns"], chart["title"],
                highlight="is_deterioration" if kind == "salience_table" else None))
    return out


# --------------------------------------------------------------------------
# Phase 1
# --------------------------------------------------------------------------
def emit_payloads(tenant: str, quarter: str, focus: str | None,
                  bundle_ids: list[str] | None) -> dict[str, Any]:
    registry = load_registry()
    context = fetch_context(tenant, quarter)

    built = [b["id"] for b in registry["bundles"] if b.get("built")]
    selected = [b for b in (bundle_ids or built) if b in built]
    if not selected:
        raise SystemExit(f"No buildable sections among {bundle_ids}. Built: {built}")

    sections = []
    for bundle_id in selected:
        print(f"  querying {bundle_id} ...", flush=True)
        gathered = gather_section(bundle_id, context, tenant)
        sections.append({
            "id": gathered["id"],
            "title": gathered["title"],
            "writing_rules": gathered["writing_rules"],
            "payload": gathered["payload"],
        })

    return {
        "context": context,
        "focus": focus,
        # The registry travels with the payloads so the caller can choose
        # sections from it. It is roughly 280 tokens: nine ids and one line
        # each. That is the entire selection surface.
        "registry": registry["bundles"],
        "sections": sections,
    }


# --------------------------------------------------------------------------
# Phase 2
# --------------------------------------------------------------------------
def assemble(tenant: str, quarter: str, narratives: dict[str, str],
             focus: str | None = None) -> dict[str, Any]:
    """Re-run the deterministic half, attach the prose, and check every figure.

    The queries are re-executed rather than cached from phase 1 so the pack
    reflects the data at the moment it is rendered. A QBR generated on demand
    should be current as of the review, which is the point of not batching them.
    """
    registry = load_registry()
    context = fetch_context(tenant, quarter)

    built = {b["id"] for b in registry["bundles"] if b.get("built")}
    unknown = set(narratives) - built
    if unknown:
        raise SystemExit(f"Narratives supplied for unknown sections: {sorted(unknown)}")

    sections = []
    for bundle_id, text in narratives.items():
        gathered = gather_section(bundle_id, context, tenant)
        bundle = load_bundle(bundle_id)
        report = grounding.check(text, gathered["payload"])

        # The qualitative check runs alongside the numeric one, never instead of
        # it. A sentence can be perfectly grounded in figures and still quote
        # something the customer never said.
        context_report = grounding.check_context(text, gathered["evidence"])

        sections.append({
            "id": bundle_id,
            "title": gathered["title"],
            "narrative": text.strip(),
            "grounded": report["ok"] and context_report["ok"],
            "figures_checked": report["checked"],
            "unverified": report["unverified"],
            "evidence": gathered["evidence"],
            "context_grounded": context_report["ok"],
            "quotes_checked": context_report["quotes_checked"],
            "citations_used": context_report["citations_used"],
            "unresolved_citations": context_report["unresolved_citations"],
            "unverified_quotes": context_report["unverified_quotes"],
            "figures": _figures(bundle, gathered["rows"], gathered["trend"],
                                gathered["breakdown"], gathered["ranking"]),
            "ranking": gathered["ranking"],
        })

    anomaly = next((s for s in sections if s["id"] == "anomalies"), None)

    kpis = [
        render.kpi("Sessions evaluated", charts.fmt(context["sessions_evaluated"], "money"),
                   f"{charts.fmt(context['sessions_qoq'], 'signed_percent')} on last quarter",
                   # Cube returns measures as strings, so coerce before comparing.
                   "up" if charts._num(context["sessions_qoq"]) >= 0 else "down"),
        render.kpi("Cart value seen", charts.fmt(context["cart_value"], "money"),
                   context["currency"]),
        render.kpi("API error rate", charts.fmt(context["api_error_rate"], "percent"),
                   "across all applications"),
        render.kpi("Loyalty points outstanding",
                   charts.fmt(context["net_points_outstanding"], "money"),
                   "issued minus burned"),
    ]

    return {
        "context": context,
        "sections": sections,
        "kpis": kpis,
        "provenance": {
            "registry_size": len(registry["bundles"]),
            "context_corpus": retrieval.corpus_summary(tenant),
            "evidence_cited": sum(len(s.get("citations_used", [])) for s in sections),
            "anomaly_candidates": anomaly["ranking"].get("candidate_count", 0) if anomaly else 0,
            "anomaly_surfaced": len(anomaly["ranking"].get("ranked", [])) if anomaly else 0,
        },
    }


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--quarter", default="2026-Q2")
    ap.add_argument("--focus", default=None)
    ap.add_argument("--bundles", default=None,
                    help="Comma-separated section ids. Defaults to every built section.")
    ap.add_argument("--emit-payloads", action="store_true",
                    help="Phase 1: query and rank, then stop.")
    ap.add_argument("--with-narratives", default=None,
                    help="Phase 2: a JSON file of {section_id: text}.")
    ap.add_argument("--json", action="store_true",
                    help="Also write the assembled pack as JSON.")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    stem = f"{args.tenant}-{args.quarter}"

    if args.emit_payloads:
        bundle_ids = args.bundles.split(",") if args.bundles else None
        print(f"Gathering data for {args.tenant}, {args.quarter}", flush=True)
        data = emit_payloads(args.tenant, args.quarter, args.focus, bundle_ids)

        path = os.path.join(OUT_DIR, f"payloads-{stem}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)

        print(f"\nWrote {path}")
        for section in data["sections"]:
            print(f"  {section['id']:24s} {len(json.dumps(section['payload'], default=str)):>6,} chars")
        print("\nWrite the prose, then rerun with --with-narratives.")
        return 0

    if args.with_narratives:
        with open(args.with_narratives, encoding="utf-8") as fh:
            narratives = json.load(fh)

        print(f"Assembling QBR for {args.tenant}, {args.quarter}", flush=True)
        pack = assemble(args.tenant, args.quarter, narratives, args.focus)

        html_path = os.path.join(OUT_DIR, f"qbr-{stem}.html")
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(render.render(pack))

        if args.json:
            with open(os.path.join(OUT_DIR, f"qbr-{stem}.json"), "w", encoding="utf-8") as fh:
                json.dump(pack, fh, indent=2, default=str)

        prov = pack["provenance"]
        print(f"\nWrote {html_path}")
        print(f"  sections: {len(pack['sections'])}")
        print(f"  anomalies: {prov['anomaly_candidates']} considered, "
              f"{prov['anomaly_surfaced']} surfaced")

        failed = []
        for section in pack["sections"]:
            state = "verified" if section["grounded"] else "UNVERIFIED"
            print(f"  {section['id']:24s} {section['figures_checked']:>3} figures  "
                  f"{section.get('quotes_checked', 0):>2} quotes  {state}")
            if not section["grounded"]:
                failed.append(section)

        if failed:
            print("\nGrounding failed.")
            for section in failed:
                if section["unverified"]:
                    tokens = ", ".join(f"'{u['token']}'" for u in section["unverified"])
                    print(f"  {section['id']}: figures not in the data: {tokens}")
                if section.get("unresolved_citations"):
                    ids = ", ".join(section["unresolved_citations"])
                    print(f"  {section['id']}: citations that do not exist: {ids}")
                if section.get("unverified_quotes"):
                    quotes = "; ".join(f'"{q}"' for q in section["unverified_quotes"])
                    print(f"  {section['id']}: quotations not found in any snippet: {quotes}")
            print("Rewrite those sections using only what the payload contains, then rerun.")
            return 1

        return 0

    ap.error("Pass either --emit-payloads or --with-narratives.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
