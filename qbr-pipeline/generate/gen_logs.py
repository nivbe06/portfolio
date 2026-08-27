"""Generate mock Talon.One raw logs.

Writes five gzipped JSONL streams under data/raw/, hive-partitioned by month and
tenant so DuckDB gets both keys as free columns and can prune on them:

    data/raw/<stream>/month=YYYY-MM/tenant=<slug>/part-000.jsonl.gz

Row-level `occurred_at` carries the real timestamp, so day grain survives the
coarser partition layout. Month partitions keep the file count at a few hundred
rather than eleven thousand.

Usage:
    python3 generate/gen_logs.py                # ~2M events, ~500 MB
    python3 generate/gen_logs.py --scale 0.05   # quick smoke run
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import random
import shutil
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import world as W  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.abspath(os.path.join(HERE, "..", "data", "raw"))

STREAMS = [
    "session_evaluations",
    "effects",
    "integration_requests",
    "loyalty_events",
    "coupon_events",
]

# Tuned so scale=1.0 lands near 2M events total.
BASE_DAILY_SESSIONS = 1940
EFFECT_RATE = 0.42          # effects fired per session evaluated
INTEGRATION_RATE = 0.21     # API calls logged per session
LOYALTY_RATE = 0.042
FIRST_NAMES = ["anna", "mike", "lars", "sofia", "tom", "priya", "jonas", "elena",
               "mark", "yusuf", "clara", "dan", "ines", "raf", "nora", "otto"]
LAST_NAMES = ["mueller", "fast", "berg", "rossi", "chen", "patel", "weber",
              "novak", "silva", "kaya", "olsen", "dubois"]


def month_key(d: dt.date) -> str:
    return f"{d.year}-{d.month:02d}"


def pick(rng: random.Random, options: list, weights: list):
    return rng.choices(options, weights=weights, k=1)[0]


def profile_for(rng: random.Random, tenant: str) -> tuple[str, str, str]:
    """Return (profile_id, email, segment). Email is deliberate PII."""
    n = rng.randint(1, 40000)
    first = FIRST_NAMES[n % len(FIRST_NAMES)]
    last = LAST_NAMES[(n // 7) % len(LAST_NAMES)]
    domain = W.TENANTS_BY_ID[tenant]["domain"]
    segment = pick(rng, W.PROFILE_SEGMENTS, W.PROFILE_SEGMENT_MIX)
    return f"prof-{tenant}-{n:06d}", f"{first}.{last}{n % 97}@{domain}", segment


class PartitionWriter:
    """Buffers rows per (stream, month, tenant) and flushes at month boundaries."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.buf: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
        self.counts: dict[str, int] = defaultdict(int)

    def add(self, stream: str, month: str, tenant: str, row: dict) -> None:
        self.buf[(stream, month, tenant)].append(row)
        self.counts[stream] += 1

    def flush(self) -> None:
        for (stream, month, tenant), rows in self.buf.items():
            if not rows:
                continue
            d = os.path.join(self.root, stream, f"month={month}", f"tenant={tenant}")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, "part-000.jsonl.gz")
            with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as fh:
                for r in rows:
                    fh.write(json.dumps(r, separators=(",", ":")))
                    fh.write("\n")
        self.buf.clear()


def generate(scale: float, seed: int) -> dict[str, int]:
    rng = random.Random(seed)

    if os.path.isdir(RAW):
        shutil.rmtree(RAW)
    os.makedirs(RAW, exist_ok=True)

    writer = PartitionWriter(RAW)
    current_month = month_key(W.START)
    seq = 0

    day = W.START
    while day <= W.END:
        mk = month_key(day)
        if mk != current_month:
            writer.flush()
            current_month = mk
            print(f"  ... {mk} written", flush=True)

        growth = W.growth_multiplier(day)

        for tenant_def in W.TENANTS:
            tenant = tenant_def["tenant"]
            apps = W.APPS_BY_TENANT[tenant]
            campaigns = W.CAMPAIGNS_BY_TENANT[tenant]
            currency = tenant_def["currency"]

            n_sessions = int(
                BASE_DAILY_SESSIONS * tenant_def["weight"] * growth * scale
            )
            if n_sessions <= 0:
                continue

            for _ in range(n_sessions):
                seq += 1
                session_seq = seq          # pin it: other streams also bump seq
                app = rng.choice(apps)
                profile_id, email, segment = profile_for(rng, tenant)
                ts = dt.datetime.combine(
                    day, dt.time(rng.randint(6, 23), rng.randint(0, 59), rng.randint(0, 59))
                )
                cart_total = round(rng.lognormvariate(3.6, 0.7), 2)
                item_count = max(1, int(rng.lognormvariate(1.0, 0.6)))

                # --- session evaluation -------------------------------------
                evaluated = [c["campaign_id"] for c in campaigns
                             if W.s2_adoption_active(c["campaign_id"], day)]
                writer.add("session_evaluations", mk, tenant, {
                    "event_id": f"se-{seq}",
                    "occurred_at": ts.isoformat(timespec="seconds"),
                    "tenant": tenant,
                    "application_id": app["application_id"],
                    "session_id": f"sess-{tenant}-{session_seq}",
                    "profile_id": profile_id,
                    "profile_email": email,          # PII, must not reach rpt_
                    "profile_segment": segment,
                    "cart_total": cart_total,
                    "currency": currency,
                    "cart_item_count": item_count,
                    "evaluated_campaigns": evaluated,
                    "ruleset_version": 2 if day >= dt.date(2026, 1, 1) else 1,
                    "latency_ms": max(3, int(rng.gauss(38, 14))),
                    "state": "closed" if rng.random() > 0.06 else "cancelled",
                })

                # --- effects ------------------------------------------------
                if rng.random() < EFFECT_RATE and campaigns:
                    camp = pick(rng, campaigns, [c["share"] for c in campaigns])
                    cid = camp["campaign_id"]

                    if not W.s2_adoption_active(cid, day):
                        pass
                    elif rng.random() > W.s2_adoption_scale(cid, day):
                        pass
                    else:
                        effect_type = rng.choice(camp["effects"])

                        # S4: notification volume triples without adding value.
                        reps = 1
                        if effect_type == "showNotification":
                            reps = max(1, round(W.s4_notification_scale(cid, day)))

                        for _r in range(reps):
                            seq += 1
                            discount = 0.0
                            points = 0
                            coupon_code = None
                            accepted = None

                            if effect_type == "setDiscount":
                                discount = round(cart_total * rng.uniform(0.05, 0.22), 2)
                            elif effect_type == "addLoyaltyPoints":
                                points = int(cart_total * rng.uniform(0.8, 1.4))
                            elif effect_type in ("acceptCoupon", "rejectCoupon"):
                                coupon_code = f"{cid.upper()[:6]}-{rng.randint(10000, 99999)}"
                                # S1: acceptance rate drops for acme winback in
                                # the QBR quarter, concentrated in 'returning'.
                                rate = W.s1_redemption_rate(tenant, cid, segment, day)
                                accepted = rng.random() < rate
                                effect_type = "acceptCoupon" if accepted else "rejectCoupon"
                                if accepted:
                                    discount = round(cart_total * rng.uniform(0.08, 0.25), 2)

                            writer.add("effects", mk, tenant, {
                                "event_id": f"ef-{seq}",
                                "occurred_at": ts.isoformat(timespec="seconds"),
                                "tenant": tenant,
                                "session_id": f"sess-{tenant}-{session_seq}",
                                "campaign_id": cid,
                                "ruleset_id": f"{cid}-rs{2 if day >= dt.date(2026, 1, 1) else 1}",
                                "effect_type": effect_type,
                                "discount_value": discount,
                                "points": points,
                                "currency": currency,
                                "coupon_code": coupon_code,
                            })

                            # --- coupon events ------------------------------
                            if coupon_code is not None:
                                seq += 1
                                writer.add("coupon_events", mk, tenant, {
                                    "event_id": f"cp-{seq}",
                                    "occurred_at": ts.isoformat(timespec="seconds"),
                                    "tenant": tenant,
                                    "campaign_id": cid,
                                    "coupon_code": coupon_code,
                                    "profile_id": profile_id,
                                    "event": "redeemed" if accepted else "rejected",
                                    "reject_reason": None if accepted else rng.choice(
                                        ["expired", "not_eligible", "limit_reached"]
                                    ),
                                })

                # --- integration requests ---------------------------------
                if rng.random() < INTEGRATION_RATE:
                    seq += 1
                    err_rate = W.s3_error_rate(app["application_id"], day)  # S3
                    failed = rng.random() < err_rate
                    writer.add("integration_requests", mk, tenant, {
                        "event_id": f"ir-{seq}",
                        "occurred_at": ts.isoformat(timespec="seconds"),
                        "tenant": tenant,
                        "application_id": app["application_id"],
                        "endpoint": rng.choice(W.ENDPOINTS),
                        "http_status": rng.choice([500, 502, 503]) if failed else 200,
                        "error_code": rng.choice(["upstream_timeout", "ruleset_eval_failed"])
                        if failed else None,
                        "latency_ms": max(5, int(rng.gauss(220 if failed else 45, 30))),
                    })

                # --- loyalty events ---------------------------------------
                if W.s5_loyalty_enabled(tenant) and rng.random() < LOYALTY_RATE:
                    seq += 1
                    burn_share = W.s6_burn_ratio(tenant, day)  # S6
                    is_burn = rng.random() < burn_share
                    delta = -int(rng.uniform(50, 400)) if is_burn else int(rng.uniform(20, 260))
                    tier_before = rng.choice(["bronze", "silver", "gold"])
                    writer.add("loyalty_events", mk, tenant, {
                        "event_id": f"ly-{seq}",
                        "occurred_at": ts.isoformat(timespec="seconds"),
                        "tenant": tenant,
                        "profile_id": profile_id,
                        "profile_email": email,      # PII, must not reach rpt_
                        "programme_id": f"{tenant}-loyalty",
                        "points_delta": delta,
                        "direction": "burn" if is_burn else "issue",
                        "tier_before": tier_before,
                        "tier_after": tier_before,
                        "reason": "redemption" if is_burn else "purchase",
                    })

        day += dt.timedelta(days=1)

    writer.flush()
    return dict(writer.counts)


def dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    return total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0,
                    help="1.0 gives roughly 2M events. Use 0.05 for a smoke run.")
    ap.add_argument("--seed", type=int, default=20260821)
    args = ap.parse_args()

    print(f"Generating {W.START} .. {W.END} at scale {args.scale}")
    counts = generate(args.scale, args.seed)

    total = sum(counts.values())
    size = dir_size(RAW)
    print("\nStream row counts")
    for s in STREAMS:
        print(f"  {s:24s} {counts.get(s, 0):>10,}")
    print(f"  {'TOTAL':24s} {total:>10,}")
    print(f"\nOn disk (gzipped): {size / 1e6:,.1f} MB")
    print(f"Uncompressed estimate: {size * 7 / 1e9:,.2f} GB")
    print(f"Output: {RAW}")


if __name__ == "__main__":
    main()
