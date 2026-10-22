## Parity: 63.0 / 100

features 63.0  (37 counted, must-haves 16 of 16 done)

## By area, weakest first
- finance                        0.0  (2 features)
- inbox                          0.0  (1 features)
- automations                    0.0  (1 features)
- integrations                   0.0  (3 features)
- inventory                      0.0  (2 features)
- notifications                  0.0  (1 features)
- marketing                      0.0  (2 features)
- storefront                     0.0  (1 features)
- platform                       0.0  (1 features)
- analytics                     50.0  (4 features)
- fraud                         60.0  (2 features)
- team                          75.0  (2 features)
- confirmation                  93.8  (6 features)
- onboarding                   100.0  (1 features)
- orders                       100.0  (6 features)
- shipping                     100.0  (1 features)
- returns                      100.0  (1 features)

## Missing, in build order
- [should] analytics: Per-product return analytics, no
- [should] automations: Automation rule builder, no  (fixed follow-up rule only)
- [should] finance: COD reconciliation of carrier payouts, no
- [should] fraud: OTP phone verification on the order form, no  (COD Rocket)
- [should] inbox: One inbox for WhatsApp Instagram Facebook TikTok, no
- [should] integrations: Shopify integration, no  (possible through the API)
- [should] integrations: WooCommerce integration, no  (possible through the API)
- [should] integrations: YouCan integration, no  (possible through the API)
- [should] inventory: Products and stock, no
- [should] notifications: Delivery status notifications to buyer, no
- [should] analytics: Per-agent performance metrics, partial  (confirmations per agent only)
- [could] analytics: Customizable dashboard and saved views, no
- [could] confirmation: AI voice calls, no
- [could] finance: Monthly invoice PDF for tax, no
- [could] inventory: Multi-warehouse routing, no
- [could] marketing: Abandoned cart recovery, no
- [could] marketing: WhatsApp broadcast campaigns, no
- [could] platform: Mobile app / offline caching, no
- [could] storefront: 1-click COD order form with upsells, no  (COD Rocket core product)
- [could] team: Screen recording and live supervision, no

## Left out on purpose (not scored)
- Meta Business Partner pre-approved templates: their partner deal with Meta
- 80+ carrier network: each carrier deal and key belongs to the merchant; we build adapters
- Mada / STC Pay online payments: Gulf payment rails; not used in Algeria
- Their customer reviews and help content: owned content

## Yours, not in the original (not scored)
- Darija reply understanding and Darija answers
- Assisted mode with merchant's own WhatsApp (prefilled one-tap messages)
- Order risk score with Algerian signals
- Delivery slot question and optional advance
- Money saved in DZD and per-wilaya return rate
- 69 wilayas and stop-desk vs home delivery
- Carrier CSV export for Yalidine ZR Maystro NOEST
- Arabic and French interface (RTL)

## Verdict

All 16 must-haves are done and no S1/S2 bug is open, but the feature score is 63, under the 80
this pack asks for "shippable". The gap is should-haves eGrow has and Mrigel does not yet:
one inbox for every channel, COD reconciliation, Shopify / WooCommerce / YouCan plugins, products
and stock, buyer delivery notifications, an automation builder.

Where it is ahead for the Algerian market (rows with original = no): Darija understanding and
answers, assisted mode with the merchant's own WhatsApp number, an explainable risk score with
Algerian signals, delivery slot and advance in the script, money saved in dinars, 69 wilayas,
Arabic RTL + French.

Layout diff against the originals was not run: no screenshots of eGrow were taken (clean-room,
no account).

## Next five to build

1. Delivery status notifications to the buyer (shipped / out for delivery) in Darija.
2. COD reconciliation: import the carrier's payout file, match delivered orders.
3. YouCan and WooCommerce connectors on top of the existing API.
4. Per-product return rate on the dashboard.
5. One inbox: show every WhatsApp conversation, not only replies to an order.
