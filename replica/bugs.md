# Bugs

Only reproduced bugs. Each has a test that failed first and passes now.

| ID | sev | title | status | test |
| --- | --- | --- | --- | --- |
| B01 | S1 | Demo store opened real WhatsApp chats | fixed | tests/test_app.py::test_demo_never_opens_whatsapp |
| B02 | S2 | First form submit after a boosted page swap was silently dropped | fixed | e2e/test_core_flow.py::test_core_loop_in_arabic |
| B03 | S2 | Wilaya written "ولاية وهران" not recognised | fixed | tests/test_algeria.py::test_parse_wilaya |
| B04 | S2 | Demo visitors could change settings, team or delete the demo store | fixed | tests/test_app.py::test_demo_never_opens_whatsapp |
| B05 | S3 | Landing: stamp printed over the chat text | fixed | screenshot S00-landing-ar-1440 |
| B06 | S3 | Language switch could redirect to another site via a forged Referer | fixed | code review (path-only redirect) |

## B01 Demo store opened real WhatsApp chats (S1)

- Steps: DEMO_MODE=1, open /demo, open any order, press "ابعت في واتساب".
- Expected: nothing is sent to a real person.
- Actual: a wa.me chat opened with the demo order's number (valid Algerian format, may belong to someone).
- Fix: demo store is flagged; the button logs the message and shows a notice instead.

## B02 Dropped submission after boosted navigation (S2)

- Steps: landing page, click "ابدا مجاناً", fill the form, submit (first time in a fresh browser).
- Expected: account created, dashboard shown.
- Actual: no POST sent, form stays (1 in 6 runs). Cause: htmx request syncing on the boosted body.
- Fix: removed htmx boosting; every page is a plain form post / full page load. 3 e2e runs in a row pass.

## B03 "ولاية وهران" not recognised (S2)

- Steps: import a CSV with wilaya "ولاية وهران".
- Expected: wilaya 31.  Actual: empty wilaya (and a higher risk score).
- Cause: "ة" was folded to "ه" before the "ولاية" prefix was stripped.

## B04 Demo store editable (S2)

- Steps: /demo, Settings, change the store name or the message template, or delete the store.
- Expected: shared demo stays intact.  Actual: changes applied for every visitor.
- Fix: settings, team, API key and deletion are locked in the demo store.

## To check (not reproduced)

- Real WhatsApp Cloud API delivery and template approval: needs the merchant's verified Meta number.
- Gemini answers on real buyer replies: needs a key; rules handle common replies without it.
- Accessibility: labels, focus and keyboard flow are tested; no automated axe scan was run (npm tooling not used in this Python project).
