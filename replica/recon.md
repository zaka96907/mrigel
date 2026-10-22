# Recon map: eGrow + COD Rocket (web SaaS)

Scope: the COD core loop: order intake, pre-dispatch confirmation (WhatsApp / calls / SMS),
dispatch to carriers, returns and COD reconciliation, analytics.
For: the user's own product for Algerian cash-on-delivery merchants (Darija, DZD,
Yalidine / ZR Express / Maystro / NOEST / Ecotrack).
Date: 2026-10-22

Clean-room: public pages only. No account, no source code, no network calls copied.

## Sources

| # | source | URL | notes |
| --- | --- | --- | --- |
| 1 | eGrow pricing | https://www.egrow.com/en/pricing | plans $59 / $99 / $199, gates, AI billed per reply, Meta fees pass-through, no free trial |
| 2 | eGrow Algeria COD article (marketing) | https://www.egrow.com/en/blog/best-cod-software-algeria-2026 | full feature tour: confirmation workflow, call center, dispatch, returns, reconciliation, inbox, KPIs |
| 3 | eGrow help center | https://help2.egrow.com/ | 12 categories; "Order stages management", carrier auto-send, WhatsApp connection |
| 4 | eGrow changelog | https://www.egrow.com/en/changelog | very active (daily); blacklist, assignment by confirmation rate, AI calls, saved filters |
| 5 | COD Rocket (Shopify app) | https://apps.shopify.com/codrocket | Moroccan (Agadir); 1-click COD form, upsells, OTP, blocking rules; Shopify only; $0/$9/$19 |
| 6 | AlgeriaTech COD article | https://algeriatech.news/?p=31058 | 95% COD, RTO 15-20% big cities, 30%+ rural, courier 300-600 DZD/shipment, confirmation cuts RTO 8-15 pts |
| 7 | DZBuild blog (local competitor) | https://dzbuild.com/blog/reduce-cod-return-rate-algeria | Algerian store builder; "phone reputation score"; tactics: call within 2h, delivery slot, partial advance |
| 8 | Emploitic job ads | https://emploitic.com/entreprises/kimland/offres-d-emploi/services/confirmateurtrice-de-commande-0da955604d5090ffb7e4cec9 | merchants still hire human "confirmateurs" |
| 9 | New wilayas (69) | https://www.tsa-algerie.com/algerie-voici-les-numeros-des-onze-nouvelles-wilayas/ | numbers 59-69 |

## Core loop

A merchant's order arrives, gets confirmed (or cancelled) with the buyer before anything ships,
confirmed orders go to the carrier, and the merchant sees confirmation rate, returns and money.

## Screens (inferred from public material)

| ID | screen | route / how to reach | purpose | key components | states seen |
| --- | --- | --- | --- | --- | --- |
| S01 | Sign in / sign up | / | access | form | empty, error |
| S02 | Home dashboard | after login | KPIs: confirmation rate, RTO, delivered, revenue | stat tiles, charts, date filter | empty (no orders), filled |
| S03 | Orders list / pipeline | Orders | every order by stage, filters, search, bulk actions | table, stage tabs, filters, saved views, search | empty, filled, filtered-empty |
| S04 | Order detail | click an order | buyer, items, address, history, stage moves, reclamations | timeline, stage buttons, notes | filled |
| S05 | Confirmation queue (agent view) | Confirmation / Call center | next order to confirm, script, call / WhatsApp buttons | queue card, script panel, outcome buttons | empty queue, filled |
| S06 | Inbox | One Inbox | WhatsApp/IG/FB/TikTok conversations in one place | conversation list, thread, composer | empty, filled |
| S07 | AI agent settings | AI Agent | model, product knowledge, tone, limits | form, toggles | default, filled |
| S08 | Automations / workflows | Automations | rules: new order -> WhatsApp -> wait 1h -> call -> human queue | rule builder | empty, filled |
| S09 | Shipping / dispatch | Shipping | send confirmed orders to carriers, labels, tracking | carrier picker, label PDF | filled, error |
| S10 | Returns & reclamations | Returns | return requests, reverse logistics | table, statuses | empty, filled |
| S11 | Finance / COD reconciliation | Finance | carrier cash vs delivered orders, invoices PDF | table, totals | filled |
| S12 | Products & inventory | Products | products, stock per warehouse | table | empty, filled |
| S13 | Team & agents | Settings > Team | users, roles, assignment rules, agent metrics | table, invite form | filled |
| S14 | Integrations | Settings > Integrations | Shopify, WooCommerce, YouCan, custom API, carriers, WhatsApp number | cards, API keys | connected, not connected |
| S15 | Customer blacklist | Customers | blocked phones, check before shipping | table, search | empty, filled |
| S16 | Pricing / billing | /pricing | plans | plan cards | - |

## Flows

```
F01 New order is confirmed automatically
    order arrives (S14 webhook) -> WhatsApp template -> buyer replies -> stage = confirmed (S03)
    happy path clicks for merchant: 0
    edge: no reply in 1h -> automated call -> human queue (S05); wrong number; buyer changes address;
          buyer asks a question; duplicate order; blacklisted phone

F02 Agent confirms by hand
    S05 queue -> open order -> call / WhatsApp -> outcome (confirmed / cancelled / no answer / call back)
    happy path clicks: 3
    edge: no answer x3, reschedule, wrong price, buyer wants exchange

F03 Ship confirmed orders
    S03 filter "confirmed" -> select -> send to carrier (S09) -> label + tracking
    happy path clicks: 4
    edge: carrier API error, unknown commune, stop-desk vs home delivery

F04 Handle a return
    carrier marks returned -> S10 -> restock / reship / blacklist buyer
    happy path clicks: 3

F05 Read performance
    S02 -> pick period -> confirmation rate, RTO, per-agent, per-product
    happy path clicks: 2

F06 Reconcile COD cash
    S11 -> import carrier payout -> match delivered orders -> mark paid
    happy path clicks: 3
```

## Components

| component | variants | states | used on |
| --- | --- | --- | --- |
| Button | primary, secondary, ghost, danger, success | default, hover, focus, disabled, loading | all |
| Stat tile | number, delta, sparkline | loading, filled | S02 |
| Order table | dense, with checkboxes | empty, loading, filled, filtered-empty | S03, S10, S11, S15 |
| Stage badge | new, pending, confirmed, cancelled, no answer, shipped, delivered, returned | - | S03, S04, S05 |
| Timeline | events with channel icon | - | S04 |
| Conversation thread | inbound, outbound, AI, system | - | S04, S06 |
| Queue card | one order at a time with outcome buttons | empty, filled | S05 |
| Filters bar | stage tabs, search, date range, wilaya | - | S03 |
| Toast | success, error | - | all |
| Modal | confirm action, import | - | S03, S09 |
| Empty state | illustration + action | - | S02, S03, S05 |

## Inferred data model

```
Store       id, name, owner_user_id, whatsapp_number, plan, settings(json)
            evidence: pricing gates (stores, numbers), integrations page   confidence: high
User        id, store_id, name, email, role (owner | admin | agent)
            evidence: team management, seats per plan                     confidence: high
Order       id, store_id, external_id, source (shopify | woo | youcan | api | manual),
            customer_name, phone, wilaya, commune, address, items(json), total, delivery_fee,
            stage, assigned_agent_id, attempts, created_at, confirmed_at, shipped_at
            evidence: order stages article, confirmation workflow, KPIs     confidence: high
OrderEvent  id, order_id, type (message | call | stage_change | note), channel, payload, at
            evidence: order detail history, call history                   confidence: medium
Message     id, order_id, direction, channel, text, ai_generated, status
            evidence: inbox, WhatsApp automation                           confidence: high
Shipment    id, order_id, carrier, tracking, status, label_url, cod_amount, fee
            evidence: shipping/labels, reconciliation                      confidence: high
Blacklist   id, store_id, phone, reason, added_at
            evidence: changelog "check customer blacklist"                 confidence: high
Product     id, store_id, name, sku, price, stock
            evidence: products & inventory                                 confidence: high
```

Relationships: Store 1-n User, Store 1-n Order, Order 1-n OrderEvent, Order 1-n Message,
Order 0-1 Shipment, Store 1-n Blacklist, Store 1-n Product.

## Feature matrix

See `features.csv`. Must: 16, should: 12, could: 9, skip: 4.

## Out of scope (cannot or should not be cloned)

- eGrow's Meta Business Partner status and pre-approved WhatsApp templates (their partner deal).
- "80+ carriers" network: each carrier integration is a separate deal / API key owned by the merchant.
- Their customer base, help-center content and reviews.
- Payment rails they integrate in the Gulf (Mada, STC Pay) — irrelevant in Algeria.

## Size

Screens 16 (we build ~10), flows 6, entities 8.
Hard parts: (1) WhatsApp delivery at scale (official Cloud API needs Meta verification and per-message fees),
(2) understanding Darija replies reliably, (3) carrier APIs differ per company.
Size: M for a solid MVP that beats them on the Algerian core loop; L for full parity.
