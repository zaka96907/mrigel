# Test plan: Mrigel

Automated: `pytest` (FastAPI TestClient against a fresh SQLite per test) and `e2e/test_core_flow.py`
(Playwright, real Chromium, against a running server). IDs map to the flows in `recon.md`.

## F01 New order is confirmed (core loop)

| ID | case | how |
| --- | --- | --- |
| F01-H1 | add order by hand, open WhatsApp with Darija message, paste "wah", order becomes confirmed | test_app::test_core_loop, e2e |
| F01-H2 | order arrives through the API, gets a risk score | test_app::test_api_create |
| F01-H3 | CSV import from an Arabic-header Excel export | test_app::test_import_csv |
| F01-H4 | cloud mode: Meta webhook reply "wah" confirms the order | test_app::test_webhook_confirms |
| F01-E1 | empty reply text does nothing | test_app::test_empty_reply |
| F01-E2 | ambiguous reply ("hmm") never auto-confirms | test_app::test_unclear_reply_not_applied |
| F01-E3 | phone written +213 / 00213 / spaces / 9 digits | test_algeria::test_phone_formats |
| F01-E4 | API retry with the same external_id returns the same order | test_app::test_api_idempotent |
| F01-E5 | webhook replayed by Meta is ignored | test_app::test_webhook_replay |
| F01-E6 | 60-character customer name, emoji in note | test_app::test_long_and_emoji |
| F01-E7 | buyer says "ma nconfirmich" (negated confirm) | test_darija |
| F01-N1 | webhook with a bad signature is refused | test_app::test_webhook_bad_signature |
| F01-N2 | API without / with a wrong key | test_app::test_api_auth |
| F01-N3 | form posted without CSRF token | test_app::test_csrf_required |
| F01-N4 | demo store never opens a real WhatsApp chat | test_app::test_demo_never_opens_whatsapp |

## F02 Agent confirms by hand (queue)

| ID | case | how |
| --- | --- | --- |
| F02-H1 | queue shows oldest new order; confirming moves to the next | test_app::test_queue_flow |
| F02-E1 | skip an order; empty queue shows the done state | test_app::test_queue_flow |
| F02-E2 | postponed order comes back when its time is due | test_app::test_postponed_returns |
| F02-N1 | impossible stage change (new -> delivered) is refused | test_app::test_bad_transition |

## F03 Ship confirmed orders

| ID | case | how |
| --- | --- | --- |
| F03-H1 | export confirmed orders as CSV (BOM, carrier columns) | test_app::test_export_and_ship |
| F03-H2 | bulk "mark shipped" moves only confirmed orders | test_app::test_export_and_ship |

## F04 Returns and blacklist

| ID | case | how |
| --- | --- | --- |
| F04-H1 | returned + "add to blacklist" raises risk of the buyer's open orders | test_app::test_return_blacklists |
| F04-H2 | removing from blacklist lowers it again | test_app::test_return_blacklists |

## F05 Dashboard

| ID | case | how |
| --- | --- | --- |
| F05-H1 | numbers match the orders (confirm rate, return rate, money saved) | test_app::test_dashboard_numbers |
| F05-E1 | brand-new store shows the empty state | test_app::test_signup_and_empty_dashboard |

## Access and accounts

| ID | case | how |
| --- | --- | --- |
| A-H1 | sign up, sign out, sign in | test_app::test_signup_and_empty_dashboard |
| A-N1 | wrong password | test_app::test_login_wrong_password |
| A-N2 | second store sees nothing of the first (pages, API, queue) | test_app::test_multi_tenant |
| A-N3 | agent cannot open settings or team | test_app::test_agent_forbidden |
| A-N4 | brute force login is rate limited | test_app::test_login_rate_limit |
| A-H2 | owner deletes the store: every row is gone | test_app::test_delete_store |
| A-H3 | saved WhatsApp token is encrypted in the database | test_app::test_secrets_encrypted |

## Jobs

| ID | case | how |
| --- | --- | --- |
| J-H1 | unanswered pending order goes to "no answer" after the wait | test_app::test_followup_job |

## Manual / browser pass

Mobile 390 px and desktop 1440 px screenshots of every screen (`tools/screens.py`), Arabic and French,
keyboard focus visible, no console errors (e2e checks console and 5xx).
Not automated: real WhatsApp delivery (needs the merchant's Meta account), real Gemini answers
(needs a key).
