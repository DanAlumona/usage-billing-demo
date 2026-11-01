#!/usr/bin/env python3
"""AI usage-based billing demo: local invoice engine plus an optional Stripe test-mode run.

    python demo.py                  # compute invoices locally (no account needed)
    python demo.py --csv usage.csv  # also export the daily usage events
    python demo.py --stripe         # replay usage into Stripe Billing (test mode) and compare

Python 3.9+, standard library only.
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from billing import CUSTOMERS, DEFAULT_PLAN, Plan, daily_tokens, invoice, money

API = "https://api.stripe.com/v1"


def print_local(plan: Plan) -> None:
    tiers = " / ".join(money(t.cents_per_m) for t in plan.tiers)
    print(f"Plan: {plan.name} ({money(plan.platform_fee_cents)} fee; {tiers} per 1M tokens)\n")
    print(f"{'Customer':<14}{'Tokens (30d)':>14}{'Usage':>11}{'Credit':>10}{'Platform':>11}{'Amount due':>12}")
    for c in CUSTOMERS:
        inv = invoice(c, plan)
        print(f"{c.name:<14}{inv.total_tokens / 1e6:>13.2f}M{money(inv.usage_cents):>11}"
              f"{money(inv.credit_cents):>10}{money(inv.platform_fee_cents):>11}{money(inv.amount_due_cents):>12}")
        lower = 0
        for tier, qty, cents in inv.tier_lines:
            if qty:
                band = f"over {lower / 1e6:g}M" if tier.up_to_tokens is None else f"up to {tier.up_to_tokens / 1e6:g}M"
                print(f"    tier {band:<12} {qty / 1e6:>8.2f}M x {money(tier.cents_per_m)}/1M = {money(cents)}")
            lower = tier.up_to_tokens or lower


def export_csv(path: str) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["customer_id", "day", "tokens"])
        for c in CUSTOMERS:
            for day, tokens in enumerate(daily_tokens(c), start=1):
                writer.writerow([c.id, day, tokens])
    print(f"\nWrote {path}")


def _flatten(prefix, value, out):
    """Encode nested params the way Stripe expects: a[b][0][c]=v."""
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}[{k}]" if prefix else k, v, out)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _flatten(f"{prefix}[{i}]", v, out)
    else:
        out.append((prefix, str(value)))
    return out


def stripe_post(key: str, path: str, params: dict) -> dict:
    data = urllib.parse.urlencode(_flatten("", params, [])).encode()
    req = urllib.request.Request(API + path, data=data, method="POST",
                                 headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as err:
        message = json.load(err).get("error", {}).get("message", err.reason)
        sys.exit(f"Stripe API error on POST {path}: {message}")


def run_stripe(plan: Plan) -> None:
    key = os.environ.get("STRIPE_API_KEY", "")
    if not key.startswith("sk_test_"):
        sys.exit("Set STRIPE_API_KEY to a Stripe test-mode secret key (sk_test_...). Live keys are refused.")

    run = str(int(time.time()))
    event_name = f"ai_tokens_k_{run}"
    print(f"\nStripe test mode, run {run}")

    # 1. A billable metric: sum of thousands of tokens per customer.
    meter = stripe_post(key, "/billing/meters", {
        "display_name": f"AI tokens (thousands) {run}",
        "event_name": event_name,
        "default_aggregation": {"formula": "sum"},
    })
    # 2. A rate card: the same graduated tiers, re-expressed per 1K tokens.
    tiers = [{"up_to": "inf" if t.up_to_tokens is None else t.up_to_tokens // 1000,
              "unit_amount_decimal": f"{t.cents_per_m / 1000:g}"} for t in plan.tiers]
    price = stripe_post(key, "/prices", {
        "currency": "usd",
        "product_data": {"name": "AI assistant tokens (per 1K)"},
        "recurring": {"interval": "month", "usage_type": "metered", "meter": meter["id"]},
        "billing_scheme": "tiered",
        "tiers_mode": "graduated",
        "tiers": tiers,
    })

    runs = []
    for c in CUSTOMERS:
        cust = stripe_post(key, "/customers", {"name": c.name, "description": c.segment,
                                               "metadata": {"demo_run": run}})
        if c.prepaid_credit_cents:
            # Customer balance stands in for a prepaid commit; it is applied to the next invoice.
            stripe_post(key, f"/customers/{cust['id']}/balance_transactions", {
                "amount": -c.prepaid_credit_cents, "currency": "usd", "description": "Prepaid usage credit"})
        sub = stripe_post(key, "/subscriptions", {"customer": cust["id"], "items": [{"price": price["id"]}],
                                                  "collection_method": "send_invoice", "days_until_due": 30})
        # 3. Usage events. The identifier makes each event idempotent if the script is re-run.
        for day, tokens in enumerate(daily_tokens(c), start=1):
            stripe_post(key, "/billing/meter_events", {
                "event_name": event_name,
                "identifier": f"{run}-{c.id}-day{day}",
                "payload": {"stripe_customer_id": cust["id"], "value": tokens // 1000},
            })
        runs.append((c, cust["id"], sub["id"]))
        print(f"  {c.name}: customer {cust['id']}, 30 usage events sent")

    # 4. Compare Stripe's invoice preview with the local engine (usage only; the platform fee is local).
    print("\nWaiting for Stripe to aggregate usage (can take a minute)...")
    print(f"{'Customer':<14}{'Local usage':>13}{'Stripe subtotal':>17}{'Local due':>12}{'Stripe due':>12}  Match")
    for c, cust_id, sub_id in runs:
        expected = invoice(c, plan)
        local_due = expected.usage_cents - expected.credit_cents
        for _ in range(12):
            preview = stripe_post(key, "/invoices/create_preview", {"customer": cust_id, "subscription": sub_id})
            if preview["subtotal"] >= expected.usage_cents - 1:
                break
            time.sleep(10)
        match = abs(preview["subtotal"] - expected.usage_cents) <= 1 and abs(preview["amount_due"] - local_due) <= 1
        print(f"{c.name:<14}{money(expected.usage_cents):>13}{money(preview['subtotal']):>17}"
              f"{money(local_due):>12}{money(preview['amount_due']):>12}  {'yes' if match else 'CHECK'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", metavar="PATH", help="export daily usage events to CSV")
    parser.add_argument("--stripe", action="store_true", help="replay usage into Stripe Billing test mode")
    args = parser.parse_args()

    print_local(DEFAULT_PLAN)
    if args.csv:
        export_csv(args.csv)
    if args.stripe:
        run_stripe(DEFAULT_PLAN)


if __name__ == "__main__":
    main()
