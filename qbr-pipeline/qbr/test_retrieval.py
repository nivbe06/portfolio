"""Tests for the account-context retrieval layer and its boundary.

Three of these defend properties that no amount of care in a prompt can
guarantee, which is the reason they are tests rather than instructions:

  * an internal document must never reach the model
  * a document belonging to another tenant must never be a candidate
  * a quotation in the prose must be something a source actually says

Run: python3 qbr/test_retrieval.py

No pytest dependency, matching qbr/test_grounding.py.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import grounding
import retrieval

TENANT = "acme-commerce"
OTHER = "nordwind-retail"

WINBACK = {"entity_label": "Winback Reactivation", "metric_name": "redemption_rate"}


# --------------------------------------------------------------------------
# The corpus and its filters
# --------------------------------------------------------------------------
def test_corpus_loads():
    docs = retrieval.load_corpus(TENANT)
    assert docs, "no context documents found for the tenant"
    assert all(d.source_id for d in docs)


def test_internal_documents_are_never_returned():
    """The filter runs before retrieval, not after generation.

    Filtering afterwards would mean the model had already read the renewal
    strategy, and a model cannot unread something.
    """
    visible = retrieval.load_corpus(TENANT)
    everything = retrieval.load_corpus(TENANT, include_internal=True)

    assert len(everything) > len(visible), (
        "the corpus has no internal document, so this test proves nothing - "
        "keep at least one, or the filter is untested"
    )
    assert all(d.visibility == "customer_safe" for d in visible)


def test_internal_content_does_not_reach_retrieval_output():
    internal = [d for d in retrieval.load_corpus(TENANT, include_internal=True)
                if d.visibility != "customer_safe"]
    forbidden_ids = {d.source_id for d in internal}

    # Query with terms taken from the internal note itself. If the filter were
    # a ranking signal rather than a filter, this is exactly what would surface
    # it.
    movements = [
        WINBACK,
        {"entity_label": "renewal", "metric_name": "redemption_rate"},
        {"entity_label": "Loyalty Tier Accelerator", "metric_name": "net_points_outstanding"},
    ]
    evidence = retrieval.retrieve_for_movements(TENANT, movements, per_movement=3)

    assert not forbidden_ids & {e["source_id"] for e in evidence}
    for item in evidence:
        assert "18%" not in item["snippet"]
        assert "Voucherify" not in item["snippet"]


def test_tenant_isolation():
    ours = {d.source_id for d in retrieval.load_corpus(TENANT)}
    theirs = {d.source_id for d in retrieval.load_corpus(OTHER)}
    assert ours and theirs
    assert not ours & theirs

    evidence = retrieval.retrieve_for_movements(TENANT, [WINBACK], per_movement=5)
    assert not {e["source_id"] for e in evidence} & theirs


def test_unknown_tenant_returns_nothing():
    assert retrieval.load_corpus("does-not-exist") == []
    assert retrieval.retrieve_for_movements("does-not-exist", [WINBACK]) == []


# --------------------------------------------------------------------------
# Retrieval behaviour
# --------------------------------------------------------------------------
def test_retrieval_is_driven_by_the_movement():
    evidence = retrieval.retrieve_for_movements(TENANT, [WINBACK])
    assert evidence, "the winback movement retrieved nothing"
    assert evidence[0]["source_id"] == "gong-2026-05-06-001"
    assert evidence[0]["explains"]["entity_label"] == "Winback Reactivation"


def test_snippet_prefers_a_verbatim_quote():
    evidence = retrieval.retrieve_for_movements(TENANT, [WINBACK])
    snippet = evidence[0]["snippet"]
    assert snippet.startswith('"') and snippet.endswith('"')
    assert "ninety days" in snippet


def test_citation_ids_are_sequential_and_unique():
    movements = [
        WINBACK,
        {"entity_label": "Loyalty Tier Accelerator", "metric_name": "net_points_outstanding"},
    ]
    evidence = retrieval.retrieve_for_movements(TENANT, movements)
    ids = [e["citation_id"] for e in evidence]
    assert ids == [f"C{i}" for i in range(1, len(ids) + 1)]
    assert len({e["source_id"] for e in evidence}) == len(evidence)


def test_no_movements_retrieves_no_evidence():
    assert retrieval.retrieve_for_movements(TENANT, []) == []


def test_a_movement_with_no_context_gets_none():
    """Silence is the correct answer when nobody wrote anything down.

    A retriever that always returns its best match would hand the model an
    irrelevant document and invite it to invent a connection.
    """
    nonsense = [{"entity_label": "Zzyzx Quarterly Widget", "metric_name": "sessions_evaluated"}]
    assert retrieval.retrieve_for_movements(TENANT, nonsense) == []


def test_commitments_are_enumerated_not_searched():
    actions = retrieval.retrieve_commitments(TENANT)
    assert len(actions) == 3
    assert {a["status"] for a in actions} == {"done", "open"}
    assert all(a["source_id"] for a in actions)


def test_corpus_summary_reports_what_was_withheld():
    summary = retrieval.corpus_summary(TENANT)
    assert summary["withheld_internal"] >= 1
    assert summary["documents_searchable"] < summary["documents_available"]


# --------------------------------------------------------------------------
# The grounding boundary
# --------------------------------------------------------------------------
def evidence():
    return retrieval.retrieve_for_movements(TENANT, [WINBACK])


def test_a_verbatim_quote_passes():
    evidence = _EVIDENCE
    text = ('The window was narrowed in April [C1]: "We cut the winback audience '
            'down to ninety days in the first week of April".')
    report = grounding.check_context(text, evidence)
    assert report["ok"], report
    assert report["quotes_checked"] == 1


def test_an_invented_quote_fails():
    evidence = _EVIDENCE
    text = 'Priya said "we are delighted with how the quarter went" [C1].'
    report = grounding.check_context(text, evidence)
    assert not report["ok"]
    assert report["unverified_quotes"]
    assert "do not appear verbatim" in grounding.format_context_failure(report)


def test_a_citation_that_was_never_retrieved_fails():
    evidence = _EVIDENCE
    report = grounding.check_context("The campaign changed in April [C9].", evidence)
    assert not report["ok"]
    assert report["unresolved_citations"] == ["C9"]


def test_paraphrase_without_quotation_marks_is_allowed():
    evidence = _EVIDENCE
    text = "Acme narrowed the eligibility window to ninety days in April [C1]."
    report = grounding.check_context(text, evidence)
    assert report["ok"], report
    assert report["quotes_checked"] == 0


def test_typographic_quotes_are_not_treated_as_fabrication():
    evidence = _EVIDENCE
    text = ('They said “We cut the winback audience down to ninety days in '
            'the first week of April” [C1].')
    report = grounding.check_context(text, evidence)
    assert report["ok"], report


def test_uncited_evidence_is_reported_but_not_a_failure():
    evidence = _EVIDENCE
    report = grounding.check_context("Redemption fell this quarter.", evidence)
    assert report["ok"]
    assert report["unused_evidence"] == ["C1"]


def test_context_is_not_a_source_of_figures():
    evidence = _EVIDENCE
    """The rule that makes the whole thing safe.

    A snippet may contain a number. That number is still not admissible as a
    figure, because `check()` reads the Cube payload and nothing else. This test
    fixes that separation so a later refactor cannot quietly merge the two.
    """
    payload = {"rows": [{"redemption_rate": 0.482258064516129}]}
    text = "Redemption was 48.2%, and ninety days is the new window."

    assert grounding.check(text, payload)["ok"]
    assert 90 not in grounding.admissible_values(payload)


_EVIDENCE = evidence()


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 - a crash is a failure too
            failures += 1
            print(f"ERROR {fn.__name__}: {type(exc).__name__}: {exc}")

    print(f"\n{len(tests) - failures}/{len(tests)} retrieval and context-grounding cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
