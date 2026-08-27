"""Prove the semantic layer is an access boundary, not just a metric dictionary.

The design document makes two claims that are easy to write and easy to leave
unimplemented:

  1. The LLM queries metrics, never tables.
  2. A query cannot cross accounts.

Both are enforced in code (public:false on every base cube, and query_rewrite in
cube.py), and both are checked here. Run against a live Cube:

    make check

A passing run is the answer to "how do you know an agent cannot read the whole
warehouse", and it is a better answer than a paragraph.
"""

from __future__ import annotations

import sys

import jwt
import requests

import cube_client as cc


def _result(name: str, passed: bool, detail: str) -> bool:
    print(f"{'PASS' if passed else 'FAIL'}  {name}")
    print(f"      {detail}")
    return passed


def test_happy_path() -> bool:
    rows = cc.run_query({
        "measures": ["qbr_campaigns.redemptions"],
        "dimensions": ["qbr_campaigns.campaign_name"],
        "filters": [{"member": "qbr_campaigns.quarter_label",
                     "operator": "equals", "values": ["2026-Q2"]}],
        "limit": 10,
    }, "acme-commerce")
    return _result(
        "an account can read its own metrics",
        len(rows) > 0,
        f"{len(rows)} campaign rows returned for acme-commerce",
    )


def test_base_cube_is_unreachable() -> bool:
    try:
        cc.run_query({"measures": ["campaign_performance.redemptions"], "limit": 5},
                     "acme-commerce")
    except Exception as exc:
        return _result(
            "a base cube cannot be queried directly",
            "Refusing to serve un-scoped members" in str(exc),
            f"refused: {str(exc)[:110]}",
        )
    return _result("a base cube cannot be queried directly", False,
                   "LEAK: the base cube answered")


def test_cross_tenant_is_empty() -> bool:
    """One account's token asking for another account's rows."""
    rows = cc.run_query({
        "measures": ["qbr_campaigns.redemptions"],
        "dimensions": ["qbr_campaigns.tenant_id"],
        "filters": [{"member": "qbr_campaigns.tenant_id",
                     "operator": "equals", "values": ["nordwind-retail"]}],
        "limit": 10,
    }, "acme-commerce")
    return _result(
        "one account cannot read another's data",
        len(rows) == 0,
        "acme's token asked for nordwind-retail and got "
        f"{len(rows)} rows; query_rewrite intersects the caller's tenant filter",
    )


def test_unsigned_scope_is_refused() -> bool:
    """A valid token with no tenant claim must fail closed."""
    token = jwt.encode({}, cc.CUBE_API_SECRET, algorithm="HS256")
    response = requests.post(
        cc.LOAD_ENDPOINT,
        headers={"Authorization": token, "Content-Type": "application/json"},
        json={"query": {"measures": ["qbr_campaigns.redemptions"], "limit": 1}},
        timeout=30,
    )
    body = response.text
    return _result(
        "a token with no tenant claim is refused",
        "tenant_id claim is required" in body,
        f"HTTP {response.status_code}, refused with the expected message",
    )


def main() -> int:
    print("Checking the semantic layer boundary against a live Cube.\n")
    try:
        cc.meta()
    except Exception as exc:
        print(f"Cube is not reachable at {cc.CUBE_URL}. Run `make serve` first.")
        print(f"  {exc}")
        return 2

    results = [
        test_happy_path(),
        test_base_cube_is_unreachable(),
        test_cross_tenant_is_empty(),
        test_unsigned_scope_is_refused(),
    ]

    passed = sum(results)
    print(f"\n{passed}/{len(results)} boundary checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
