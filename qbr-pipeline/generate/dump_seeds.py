"""Dump the world's static reference data to dbt seeds.

The logs describe behaviour; they do not carry account metadata like plan tier,
entitlements, or whether a campaign sits behind a paid feature. That comes from
the CRM side, which here is world.py. Dumping rather than hand-maintaining the
CSVs keeps world.py the single source of truth for both.
"""

from __future__ import annotations

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import world as W  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SEEDS = os.path.abspath(os.path.join(HERE, "..", "dbt", "seeds"))


def write(name: str, header: list[str], rows: list[list]) -> None:
    os.makedirs(SEEDS, exist_ok=True)
    path = os.path.join(SEEDS, f"{name}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    print(f"  {name}.csv  {len(rows)} rows")


def main() -> None:
    write(
        "seed_tenants",
        ["tenant", "tenant_name", "domain", "plan_tier", "country", "currency",
         "entitlements", "has_loyalty_entitlement", "has_referrals_entitlement"],
        [[t["tenant"], t["name"], t["domain"], t["plan_tier"], t["country"],
          t["currency"], "|".join(t["entitlements"]),
          "loyalty" in t["entitlements"], "referrals" in t["entitlements"]]
         for t in W.TENANTS],
    )

    write(
        "seed_applications",
        ["application_id", "tenant", "channel", "application_name"],
        [[a["application_id"], a["tenant"], a["channel"], a["name"]]
         for a in W.APPLICATIONS],
    )

    write(
        "seed_campaigns",
        ["campaign_id", "tenant", "campaign_name", "campaign_type", "is_paid_feature"],
        [[c["campaign_id"], c["tenant"], c["name"], c["campaign_type"], c["paid_feature"]]
         for c in W.CAMPAIGNS],
    )

    write(
        "seed_rulesets",
        ["ruleset_id", "campaign_id", "ruleset_version", "activated_on"],
        [[r["ruleset_id"], r["campaign_id"], r["version"], r["activated_on"].isoformat()]
         for r in W.RULESETS],
    )

    # Effect-type reference, including the weight the salience ranker uses to
    # separate "moves money" from "moves a pixel".
    write(
        "seed_effect_types",
        ["effect_type", "is_monetary", "value_weight"],
        [[k, v["monetary"], v["value_weight"]] for k, v in W.EFFECT_TYPES.items()],
    )

    print(f"\nSeeds written to {SEEDS}")


if __name__ == "__main__":
    main()
