"""Unit tests for the pricing engine. Run: python -m unittest -v"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

from billing import CUSTOMERS, DEFAULT_PLAN, Plan, Tier, daily_tokens, invoice, money, price_tiers
from demo import _flatten

ROOT = Path(__file__).resolve().parent.parent
BY_ID = {c.id: c for c in CUSTOMERS}


class PriceTiersTest(unittest.TestCase):
    def test_zero_usage_costs_nothing(self):
        self.assertEqual([cents for _, _, cents in price_tiers(0, DEFAULT_PLAN.tiers)], [0, 0, 0])

    def test_usage_inside_first_tier(self):
        lines = price_tiers(10_000_000, DEFAULT_PLAN.tiers)
        self.assertEqual([(qty, cents) for _, qty, cents in lines], [(10_000_000, 2_000), (0, 0), (0, 0)])

    def test_exact_tier_boundary_stays_in_lower_tier(self):
        lines = price_tiers(50_000_000, DEFAULT_PLAN.tiers)
        self.assertEqual([qty for _, qty, _ in lines], [50_000_000, 0, 0])

    def test_graduated_across_all_tiers(self):
        # 50M x $2.00 + 150M x $1.50 + 50M x $1.00 = $100 + $225 + $50
        lines = price_tiers(250_000_000, DEFAULT_PLAN.tiers)
        self.assertEqual([(qty, cents) for _, qty, cents in lines],
                         [(50_000_000, 10_000), (150_000_000, 22_500), (50_000_000, 5_000)])

    def test_rounds_half_up_to_the_cent(self):
        tiers = (Tier(None, 1),)  # 1 cent per 1M tokens
        self.assertEqual(price_tiers(500_000, tiers)[0][2], 1)  # exactly half a cent -> 1
        self.assertEqual(price_tiers(499_999, tiers)[0][2], 0)


class InvoiceTest(unittest.TestCase):
    def test_readme_amounts(self):
        """The amounts printed in the README, which Stripe's test-mode invoices matched."""
        expected = {"northwind": (45_300_000, 9_060, 0, 59_060),
                    "lumen": (188_750_000, 30_813, 25_000, 55_813),
                    "acme": (339_750_000, 46_475, 0, 96_475)}
        for cid, (tokens, usage, credit, due) in expected.items():
            with self.subTest(customer=cid):
                inv = invoice(BY_ID[cid])
                self.assertEqual((inv.total_tokens, inv.usage_cents, inv.credit_cents, inv.amount_due_cents),
                                 (tokens, usage, credit, due))

    def test_credit_never_exceeds_usage(self):
        cheap = Plan("cheap", 50_000, (Tier(None, 1),))
        inv = invoice(BY_ID["lumen"], cheap)
        self.assertEqual(inv.credit_cents, inv.usage_cents)
        self.assertEqual(inv.amount_due_cents, 50_000)  # the platform fee is still due

    def test_usage_is_deterministic(self):
        self.assertEqual(daily_tokens(BY_ID["acme"]), daily_tokens(BY_ID["acme"]))
        self.assertEqual(len(daily_tokens(BY_ID["acme"])), 30)


class HelpersTest(unittest.TestCase):
    def test_money(self):
        self.assertEqual(money(123_456), "$1,234.56")

    def test_flatten_matches_stripe_form_encoding(self):
        out = []
        _flatten("", {"recurring": {"interval": "month"}, "tiers": [{"up_to": 5}]}, out)
        self.assertEqual(out, [("recurring[interval]", "month"), ("tiers[0][up_to]", "5")])


class StripeSafetyTest(unittest.TestCase):
    def test_live_key_is_refused_before_any_api_call(self):
        env = dict(os.environ, STRIPE_API_KEY="sk_live_not_a_real_key")
        result = subprocess.run([sys.executable, "demo.py", "--stripe"], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Live keys are refused", result.stderr)


if __name__ == "__main__":
    unittest.main()
