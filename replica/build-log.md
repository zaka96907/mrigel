# Build log

| screen | date | status | missing | harder than expected |
| --- | --- | --- | --- | --- |
| S00 landing | 2026-10-22 | done | - | stamp overlapping the chat (fixed) |
| S01 sign up / sign in | 2026-10-22 | done | email verification, password reset | - |
| S02 dashboard | 2026-10-22 | done | per-product returns | ledger strip border radius in RTL |
| S03 orders list | 2026-10-22 | done | saved views | table to cards on mobile |
| S04 order detail | 2026-10-22 | done | - | - |
| S05 confirmation queue | 2026-10-22 | done | - | - |
| S06 inbox | - | not built | whole screen | - |
| S07 AI settings | 2026-10-22 | done (inside settings) | - | - |
| S08 automations | - | not built | rule builder (one fixed follow-up rule exists) | - |
| S09 shipping | 2026-10-22 | partial | carrier API adapters, labels | carrier docs not public |
| S10 returns | 2026-10-22 | partial | reverse logistics; returns are a stage + blacklist | - |
| S11 finance | - | not built | COD reconciliation | - |
| S12 products | - | not built | products and stock | - |
| S13 team | 2026-10-22 | done | - | - |
| S14 integrations / settings | 2026-10-22 | done | Shopify / Woo / YouCan apps | - |
| S15 blacklist | 2026-10-22 | done | - | - |
| privacy | 2026-10-22 | done | - | - |

Removed htmx boosting after it dropped the first form submit in 1 of 6 browser runs (bug B02).

## 2026-10-22 — from 63 to 93.8

Built the should-haves eGrow and COD Rocket have and Mrigel did not: products and stock (app/catalog.py),
delivery notices and a message queue (app/notify.py), automation rules (app/rules.py), COD
reconciliation and the monthly PDF (app/finance.py, app/pdf.py), the public order form with upsell,
OTP and abandoned carts (app/storefront.py, app/routes/shop.py), Shopify / WooCommerce / YouCan
webhooks (app/shops.py), Messenger and Instagram (app/meta.py) in a unified inbox, campaigns
(app/campaigns.py), per-agent and per-product numbers, saved views, dashboard layout, installable
web app. 35 new tests (tests/test_v2.py) and one browser test for the order form. Parity 93.8.
