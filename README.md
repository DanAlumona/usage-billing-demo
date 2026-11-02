# Usage-based billing for an AI product

**Live demo:** https://danalumona.github.io/usage-billing-demo/ · Built by [Daniel Alumona](https://www.linkedin.com/in/danielalumona)

A small, dependency-free demo of how an AI company might bill customers on usage. Customers pay a platform fee plus graduated token tiers, and prepaid credit draws down usage charges. It has three parts:

| File | What it does |
|---|---|
| `billing.py` | The pricing engine: billable metric, rate card, graduated tiers, credits, invoice. Pure functions, integer cents. |
| `demo.py` | Prints the invoices locally, optionally exports the usage events to CSV, and can replay the same usage into **Stripe Billing in test mode** to check Stripe's invoice against the local engine. |
| `index.html` | A browser simulator of the same engine. Change the rate card or credit and every invoice updates. Open it directly; no install needed. |

## The scenario

Three customers of an AI assistant, 30 days of token usage each:

| Customer | Profile | Tokens (30 days) |
|---|---|---|
| Northwind AI | Seed stage, pay as you go | 45.30M |
| Lumen Labs | Series B, $250 prepaid credit | 188.75M |
| Acme Capital | Enterprise, high volume | 339.75M |

The rate card:
- $500 platform fee per month.
- Tokens priced per 1M: **$2.00** for 0-50M, **$1.50** for 50-200M, **$1.00** above 200M (graduated).
- Credit applies to usage, not to the platform fee.

## Expected output

```
python demo.py

Customer        Tokens (30d)      Usage    Credit   Platform  Amount due
Northwind AI          45.30M     $90.60     $0.00    $500.00     $590.60
Lumen Labs           188.75M    $308.13   $250.00    $500.00     $558.13
Acme Capital         339.75M    $464.75     $0.00    $500.00     $964.75
```

(The script also prints a per-tier breakdown under each customer.)

Lumen's usage: 50M x $2.00 = $100.00, plus 138.75M x $1.50 = $208.125, rounded half up to $208.13.

## Run it

Python 3.9+ is required. There are no packages to install.

```bash
python demo.py
```

```bash
python demo.py --csv usage.csv
```

### Optional: check against Stripe Billing (test mode)

1. Create a free Stripe account and copy the **test-mode** secret key (`sk_test_...`) from the Developers > API keys page. The script refuses live keys.
2. Set the key and run:

```bash
set STRIPE_API_KEY=sk_test_...
```

```bash
python demo.py --stripe
```

The script then:
1. Creates a **billing meter**: the sum of thousands of tokens per customer.
2. Creates a **graduated tiered price** on that meter (the same tiers, expressed per 1K tokens).
3. For each customer: creates the customer, adds the prepaid credit as a customer balance, starts a subscription, and sends 30 daily **meter events** (each with an idempotency identifier).
4. Pulls Stripe's **invoice preview** for each subscription and compares it with the local engine.

Notes:
- **Platform fee:** the Stripe run covers usage only, because the $500 fee is modelled locally.
- **Timing:** the 30 days of events are all sent "now", so they land in the current billing period.
- **Delays:** Stripe aggregates meter events asynchronously, so the script polls for up to two minutes.
- **Rounding:** a 1-cent difference can appear where Stripe's rounding differs from round-half-up.
- **Clean-up:** everything is created in test mode; delete or deactivate it from the Stripe dashboard afterwards.

## Verified against Stripe (2 Nov 2026)

`python demo.py --stripe`, run against a Stripe sandbox. Stripe's invoice previews match the local engine to the cent:

```
Customer        Local usage  Stripe subtotal   Local due  Stripe due  Match
Northwind AI         $90.60           $90.60      $90.60      $90.60  yes
Lumen Labs          $308.13          $308.13      $58.13      $58.13  yes
Acme Capital        $464.75          $464.75     $464.75     $464.75  yes
```

These are usage-only figures. The $500 platform fee is modelled locally, and Lumen's $250 prepaid credit is applied by Stripe as a customer balance.

## How this maps to usage-billing platform concepts

| Concept | Here |
|---|---|
| Usage event | One record per customer per day: `{customer, tokens}` |
| Billable metric | Sum of tokens over the billing period (a Stripe meter in `--stripe` mode) |
| Rate card | Platform fee plus graduated token tiers (`DEFAULT_PLAN`) |
| Commit / prepaid credit | Credit that draws down usage charges (a customer balance in Stripe) |
| Invoice | Tier lines, minus credit, plus platform fee |

## Design choices

- **Integer cents** throughout, so the Python engine, the browser simulator and Stripe can be compared exactly.
- **Deterministic usage** (no randomness), so every run and every reviewer sees the same numbers.
- **Idempotent events:** each meter event has a unique identifier, so re-sending doesn't double count.
- **Standard library only**, so it runs anywhere Python does.

## Ideas to extend

- Compare pricing models for the same usage: flat per-token, tiered, and commit with overage.
- Add seat-based plus usage hybrids, or per-model pricing (different prices for different AI models).
- Alert when a customer's prepaid credit is about to run out.
