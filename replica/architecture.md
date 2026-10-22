# Architecture: the Algerian COD confirmation app (a rebuild of eGrow's core confirmation loop)

## Stack

| layer | choice | why |
| --- | --- | --- |
| web | FastAPI + Jinja2 server-rendered pages + HTMX | Python as required; no JS build step; fast pages on weak 4G connections |
| styling | hand-written CSS from design tokens (`static/app.css`), logical properties for RTL | full control of Arabic RTL + French LTR, no CDN at runtime |
| database | SQLAlchemy 2.0; SQLite by default, Postgres (Neon / Supabase free tier) via `DATABASE_URL` | zero setup locally, one env var for production |
| auth | email + password (bcrypt), signed session cookie (Starlette `SessionMiddleware`) | no third-party account needed by the merchant |
| AI | Google Gemini (`google-genai`), optional, merchant's or our key | available in Algeria; rules engine handles common Darija replies without any key |
| WhatsApp | mode 1 "assisted": one-tap `wa.me` prefilled messages from the merchant's own phone; mode 2 "cloud": Meta WhatsApp Cloud API | mode 1 works today with zero Meta setup; mode 2 when the merchant is verified |
| payments | none in-app; plans billed manually (BaridiMob / CCP) | Stripe does not serve Algerian merchants |
| email | none for MVP | merchants are reached on WhatsApp |
| jobs | in-process loop every 60 s + `POST /tasks/run` (token) for an external cron | follow-ups for unanswered orders; works on a sleeping free host via cron ping |
| hosting | Docker image; Render / Railway / Fly free tiers; can move to an Algerian host later (Law 18-07) | one container, one database |

## Schema

Tables: 6. Access rules: data-layer checks — every query goes through `scoped(store_id)`.
IDs are UUID strings (portable SQLite/Postgres). Money is integer dinars (`*_dzd`), the only
currency. Times are UTC; display in Africa/Algiers (UTC+1, no DST).

See `replica/schema.sql` (generated from the models).

## API

| method path | does | who | input | output | flow |
| --- | --- | --- | --- | --- | --- |
| GET / | landing, or dashboard when signed in | public | - | HTML | - |
| GET/POST /signup | create store + owner | public | store, name, email, password | redirect | - |
| GET/POST /login, POST /logout | session | public | email, password | redirect | - |
| GET /lang/{code} | switch ar / fr | any | - | redirect | - |
| GET /dashboard | KPIs, money saved, per-wilaya returns | member | period | HTML | F05 |
| GET /orders | list by stage, search, wilaya filter | member | stage, q, wilaya | HTML | F01-F03 |
| GET/POST /orders/new | add an order by hand | member | form | redirect | F01 |
| GET /orders/{id} | detail, timeline, thread, risk | member | - | HTML | F01, F02 |
| POST /orders/{id}/stage | move stage | member | stage, reason | redirect / HTMX | F02 |
| POST /orders/{id}/send | log + open WhatsApp (assisted) or send (cloud) | member | template | wa.me URL / status | F01, F02 |
| POST /orders/{id}/reply | paste/receive buyer reply, classify, suggest answer | member | text | HTMX fragment | F01 |
| POST /orders/{id}/note | add note | member | text | HTMX | F02 |
| GET /queue | next order to confirm, one at a time | member | - | HTML | F02 |
| GET/POST /import | CSV upload, column mapping preview | member | file | report | F01 |
| GET /export.csv | confirmed orders for a carrier | member | carrier | CSV | F03 |
| POST /orders/ship | mark selected confirmed as shipped | member | ids | redirect | F03 |
| GET/POST /blacklist | list / add / remove phones | member | phone, reason | HTML | F04 |
| GET/POST /settings | store, WhatsApp mode, keys, templates, slots, advance | owner | form | HTML | - |
| GET/POST /team | members (owner adds agents) | owner | name, email, password | HTML | - |
| POST /api/v1/orders | intake from any site / sheet script | API key | JSON order | 201 JSON | F01 |
| GET /webhooks/whatsapp | Meta verification | Meta | hub.* | challenge | F01 |
| POST /webhooks/whatsapp | inbound buyer messages | Meta (signed) | JSON | 200 | F01 |
| POST /tasks/run | run due follow-ups | cron token | - | JSON | F01 |
| GET /health | liveness | public | - | JSON | - |

Webhooks in: WhatsApp Cloud API (`X-Hub-Signature-256` verified with the app secret).
Webhooks out: none yet.
Jobs: `followups` every 60 s — orders `pending` with no reply after `followup_minutes` get
another message (cloud) or go back to the agent queue as `no_answer` (assisted); after
`max_attempts` they are flagged for a call.

## The parts that bite

- phone numbers: Algerian mobiles written 0555..., 555..., +213 555..., 00213...; normalise to
  `0XXXXXXXXX` for display and `213XXXXXXXXX` for WhatsApp; reject non-mobile for WhatsApp.
- duplicates: same phone + same total within 24 h is flagged; `(store_id, external_id)` unique.
- idempotency: WhatsApp webhook message ids stored unique; a replayed webhook is ignored.
- multi-tenancy: one helper scopes every query by `store_id`; tested with a second store.
- time zones: stored UTC, shown Africa/Algiers.
- Arabic text: RTL layout with logical CSS; numbers kept LTR (`dir="ltr"` on phones and prices).
- CSV: Excel exports in UTF-8 with BOM or Windows-1256; sniff the delimiter; map Arabic/French headers.
- AI: rules first (instant, free), LLM only for unclear replies; time-out 8 s; never auto-confirm on low confidence.
- WhatsApp policy: business-initiated messages need approved templates in cloud mode; assisted mode
  sends from the merchant's phone, one tap per order, no bulk automation (avoids bans).
- data protection: buyer names/phones are personal data (Law 18-07); keep them scoped, deletable,
  and plan an Algerian host.

## Build order

1. Vertical slice: signup/login, add order, order detail with risk score, one-tap WhatsApp
   message, paste reply -> Darija intent -> stage change. Tables: stores, users, orders,
   order_events. Screens S01, S03, S04.
2. Must-haves: orders list + filters, queue (S05), CSV import, API intake, blacklist (S15),
   carrier export (S09), dashboard (S02), settings + team (S13, S14), messages table, cloud webhook.
3. Should-haves: delivered/returned marking, per-agent and per-product stats, slot + advance in script.
4. Fixes from replica-entrepreneur: all 8 are in steps 1-3; pricing in DZD goes to the landing page.
