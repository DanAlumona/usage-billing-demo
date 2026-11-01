"""Usage-based pricing engine for an AI assistant product.

Pure functions only, so the same maths can be checked by hand, by the browser
simulator (index.html) and against a Stripe test-mode invoice preview.

Units: usage is metered in tokens; prices are integer US cents per 1M tokens.
Money is kept in integer cents throughout to avoid floating-point drift.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

DAYS = 30


@dataclass(frozen=True)
class Tier:
    up_to_tokens: Optional[int]  # upper bound of the tier; None = no upper bound
    cents_per_m: int  # price in US cents per 1M tokens


@dataclass(frozen=True)
class Plan:
    name: str
    platform_fee_cents: int
    tiers: Tuple[Tier, ...]


# Hybrid model common in AI pricing: a flat platform fee plus graduated token tiers.
DEFAULT_PLAN = Plan(
    name="Hybrid: platform fee + graduated token tiers",
    platform_fee_cents=50_000,
    tiers=(Tier(50_000_000, 200), Tier(200_000_000, 150), Tier(None, 100)),
)


@dataclass(frozen=True)
class Customer:
    id: str
    name: str
    segment: str
    base_tokens_per_day: int
    prepaid_credit_cents: int = 0


CUSTOMERS = (
    Customer("northwind", "Northwind AI", "Seed stage, pay as you go", 1_200_000),
    Customer("lumen", "Lumen Labs", "Series B, $250 prepaid credit", 5_000_000, 25_000),
    Customer("acme", "Acme Capital", "Enterprise, high volume", 9_000_000),
)


@dataclass(frozen=True)
class Invoice:
    customer: Customer
    total_tokens: int
    tier_lines: Tuple[Tuple[Tier, int, int], ...]  # (tier, tokens billed in tier, cents)
    usage_cents: int
    credit_cents: int
    platform_fee_cents: int

    @property
    def amount_due_cents(self) -> int:
        return self.platform_fee_cents + self.usage_cents - self.credit_cents


def daily_tokens(customer: Customer, days: int = DAYS) -> List[int]:
    """Deterministic, slightly uneven daily usage, so every run produces the same numbers."""
    step = customer.base_tokens_per_day // 20
    return [customer.base_tokens_per_day + ((day * 37) % 11) * step for day in range(1, days + 1)]


def price_tiers(total_tokens: int, tiers: Tuple[Tier, ...]) -> Tuple[Tuple[Tier, int, int], ...]:
    """Graduated pricing: each tier prices only the tokens that fall inside it."""
    lines, lower = [], 0
    for tier in tiers:
        upper = total_tokens if tier.up_to_tokens is None else min(total_tokens, tier.up_to_tokens)
        qty = max(0, upper - lower)
        cents = (qty * tier.cents_per_m + 500_000) // 1_000_000  # round half up to the cent
        lines.append((tier, qty, cents))
        if tier.up_to_tokens is not None:
            lower = tier.up_to_tokens
    return tuple(lines)


def invoice(customer: Customer, plan: Plan = DEFAULT_PLAN) -> Invoice:
    total = sum(daily_tokens(customer))
    lines = price_tiers(total, plan.tiers)
    usage = sum(cents for _, _, cents in lines)
    credit = min(customer.prepaid_credit_cents, usage)  # credits draw down usage, not the platform fee
    return Invoice(customer, total, lines, usage, credit, plan.platform_fee_cents)


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"
