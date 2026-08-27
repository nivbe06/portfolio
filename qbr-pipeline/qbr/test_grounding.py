"""Tests for the grounding check.

Run: python3 qbr/test_grounding.py

No pytest dependency. The grounding check is the control that stops a
hallucinated figure reaching a customer, so it is the one piece of Python here
that genuinely needs tests: it fails in both directions, and both failures are
bad. Too strict and every section gets regenerated for no reason. Too loose and
it stops being a control at all.
"""

from __future__ import annotations

import sys

import grounding

PAYLOAD = {
    "rows": [
        {
            "campaign_name": "Winback Reactivation",
            "redemption_rate": 0.4866,
            "prior_redemption_rate": 0.6176,
            "redemptions": 2617,
            "redemption_attempts": 5378,
            "discount_value": 18432.55,
        },
        {
            "campaign_name": "Basket Boost",
            "redemption_rate": 0.61,
            "discount_value": 90210.0,
        },
    ]
}

CASES: list[tuple[str, bool, str]] = [
    # Accept: legitimate renderings of payload figures.
    ("Redemption rate fell to 49% from 62%.", True,
     "a ratio of 0.4866 may be written as 49%"),
    ("Redemption rate fell to 48.7% from 61.8%.", True,
     "one decimal place is still correct rounding"),
    ("Winback delivered 2,617 redemptions from 5,378 attempts.", True,
     "thousands separators"),
    ("Discount value reached 18,432.55.", True, "exact decimal"),
    ("Discount value was about 18.4k.", True, "thousands shorthand"),
    ("Discount value hit 90,210.", True, "figure from the second row"),
    ("Rate dropped 13 points, from 62% to 49%.", True,
     "a difference between two payload figures is derivable"),
    ("Redemption rate fell 21% against last quarter.", True,
     "a relative change between two payload figures is derivable"),
    ("Across the top 3 campaigns, results held.", True,
     "small integers are prose, not claims about data"),
    ("In 2026 the account grew.", True, "a year is a label"),

    # Reject: figures the payload does not support.
    ("Redemption rate fell to 24%.", False, "not a rounding of anything present"),
    ("We saw 9,412 redemptions.", False, "invented count"),
    ("Attempts rose to 5,900.", False,
     "plausible and near the real 5,378, which is exactly why it must fail"),

    # Regressions. Both of these were accepted by earlier versions of the check,
    # and both are the failure that matters: a fabricated figure, close enough
    # to the real one to look right, in front of a customer.
    ("Redemption rate fell to 44.2%.", False,
     "REGRESSION: real value is 48.66%. Rounding the claim rather than the "
     "payload let anything near 44 through"),
    ("Redemption rate fell to 48.9%.", False,
     "REGRESSION: one decimal place out from the real 48.7%. A figure written "
     "to a decimal place must be right to a decimal place"),
    ("Prior rate was 61.2%.", False,
     "REGRESSION: real prior is 61.76%, which rounds to 61.8, not 61.2"),
]


def main() -> int:
    failures = 0

    for text, should_accept, why in CASES:
        report = grounding.check(text, PAYLOAD)
        behaved = report["ok"] == should_accept

        if not behaved:
            failures += 1
            got = "accepted" if report["ok"] else "rejected"
            want = "accept" if should_accept else "reject"
            print(f"FAIL  wanted {want}, {got}: {why}")
            print(f"      text: {text}")
            if report["unverified"]:
                print(f"      unverified: {[u['token'] for u in report['unverified']]}")

    total = len(CASES)
    print(f"\n{total - failures}/{total} grounding cases behaved as intended")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
