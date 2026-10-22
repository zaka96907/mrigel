## Parity: 93.8 / 100

features 93.8  (37 counted, must-haves 16 of 16 done)

## By area, weakest first
- inbox                         50.0  (1 features)
- platform                      50.0  (1 features)
- inventory                     66.7  (2 features)
- team                          75.0  (2 features)
- finance                       83.3  (2 features)
- confirmation                  93.8  (6 features)
- onboarding                   100.0  (1 features)
- orders                       100.0  (6 features)
- fraud                        100.0  (2 features)
- shipping                     100.0  (1 features)
- analytics                    100.0  (4 features)
- returns                      100.0  (1 features)
- automations                  100.0  (1 features)
- integrations                 100.0  (3 features)
- notifications                100.0  (1 features)
- marketing                    100.0  (2 features)
- storefront                   100.0  (1 features)

## Missing, in build order
- [should] inbox: One inbox for WhatsApp Instagram Facebook TikTok, partial  (WhatsApp + Messenger + Instagram in one inbox; TikTok has no messaging API open to Algerian merchants; Meta channels not yet tested against a live page)
- [could] confirmation: AI voice calls, no
- [could] inventory: Multi-warehouse routing, no
- [could] team: Screen recording and live supervision, no
- [could] finance: Monthly invoice PDF for tax, partial  (bilingual monthly statement PDF; not a fiscal invoice)
- [could] platform: Mobile app / offline caching, partial  (installable web app (manifest + service worker), shell cached offline; no native app)

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

93.8 / 100, above the 80 this pack asks for "shippable" and above the 90 target. All 16 must-haves
are done, every should-have is done except the inbox (WhatsApp, Messenger and Instagram are in;
TikTok is not, because TikTok has no messaging API open to Algerian merchants).

What is honestly still unproven, and must be checked with real accounts before selling:
- Shopify, WooCommerce and YouCan webhooks are tested with the payload shapes in their public docs,
  not yet with a live store.
- WhatsApp Cloud API (notices, campaigns, OTP template) and Messenger/Instagram replies are tested
  with the Meta API mocked, not yet with a verified number or page.
- The monthly PDF is a statement for the merchant's books, not a fiscal invoice.
- The "mobile app" is an installable web app with an offline shell, not a store app.

Not built: AI voice calls, multi-warehouse routing, screen recording of agents.

Layout diff against the originals was not run: no screenshots of eGrow were taken (clean-room,
no account).
