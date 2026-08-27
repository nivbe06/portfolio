# Account context: the qualitative half of a QBR

A QBR is not a numbers dump. The account team already knows things the warehouse
cannot: what the customer said on a call, what was promised last quarter, which
support case is still sore. Those facts live in Gong and Salesforce, not in a
fact table.

This directory is a **mock** of that corpus - four sources, hand-written, no
external service and no network. It exists so the retrieval boundary can be
built and demonstrated. Nothing here describes a real company, a real call or a
real person.

## Sources

| Directory | Stands in for | Shape |
|---|---|---|
| `gong/` | Call recordings and summaries | Summary plus a handful of verbatim quotes with speaker and timestamp |
| `salesforce/notes/` | CSM account notes | Free text, dated |
| `salesforce/cases/` | Support cases | Status, severity, free text |
| `commitments/` | Action items agreed at the last QBR | Structured, with an owner and a status |

## Frontmatter

Every document carries the same header. The fields are not decoration; the
retriever and its tests read all of them.

```yaml
source: gong                       # gong | salesforce_note | salesforce_case | commitment
source_id: gong-2026-05-06-001     # stable, and cited in the rendered pack
date: 2026-05-06
tenant_id: acme-commerce           # retrieval never crosses this
participants: [...]                # rendered as provenance
entities: [Winback Reactivation]   # joins a document to an anomaly row
visibility: customer_safe          # customer_safe | internal
```

## `visibility` is the important one

Real account notes contain things a customer must never read: renewal risk,
pricing headroom, an opinion about their staff. That content is in this corpus
on purpose, because a retrieval layer that has only safe documents in it proves
nothing.

`visibility: internal` documents are filtered out **before** the model is given
anything, not after it writes. A test asserts that no internal `source_id` and
no sentence from an internal document reaches a rendered pack. See
`qbr/retrieval.py` and `qbr/test_retrieval.py`.
