# Backend checklist: Mrigel

## Auth
- [x] email + password sign up and sign in, bcrypt hashes
- [x] signed session cookie, http-only, SameSite=Lax, Secure in production (`SECURE_COOKIES=1`)
- [x] roles: owner / agent; one guard (`owner_only`) on settings, team, deletion
- [x] account deletion that deletes everything (store, orders, messages, team) — `test_delete_store`
- [ ] email verification and password reset: no email provider yet. Today the owner resets an
      agent by adding them again; an owner who forgets the password needs the database operator.

## Database
- [x] tables created from the models at start; schema in `replica/schema.sql`
- [ ] migrations: add Alembic before the first schema change in production
- [x] every query scoped by store (`scoped_order`, store_id filters, API key → store) — `test_multi_tenant`
- [x] seed script with invented data (`python -m app.seed`), demo store locked and never sends
- [ ] backups: turn on the host's daily backups (Render / Neon / Supabase all offer them)

## Payments
- Not in the app. Stripe does not serve Algerian merchants; plans are paid by BaridiMob / CCP and
  set by hand (`stores.plan`).

## Jobs
- [x] follow-ups every 60 s in-process, or `POST /tasks/run` with `X-Cron-Token` from a cron service
- [x] times stored in UTC, shown in Africa/Algiers

## Integrations
| integration | API | keys | notes |
| --- | --- | --- | --- |
| WhatsApp (assisted) | wa.me links | none | one tap per order from the merchant's own phone; no bulk sending |
| WhatsApp Cloud API | graph.facebook.com/{version}/{phone_number_id}/messages | merchant's token, app secret, verify token | first message outside 24 h needs an approved template; webhook signature checked |
| Google Gemini | google-genai | store key or `GEMINI_API_KEY` | only for unclear replies; 8 s timeout; never auto-confirms under 0.8 confidence |
| Carriers | CSV export | none | per-carrier API adapters not built (no official docs verified) |

## Security checklist
- [x] secrets only in env vars, `.env*` ignored, `.env.example` lists every variable
- [x] merchants' third-party keys encrypted at rest (Fernet, key derived from SECRET_KEY) — `test_secrets_encrypted`
- [x] input validated on the server on every route (lengths, numbers, stages, enums, JSON shape)
- [x] authorisation on every read and write, tested with a second store and an agent
- [x] CSRF token on every form post — `test_csrf_required`
- [x] rate limits: login 10 / 5 min, sign up 5 / h, team 20 / h, API 120 / min per IP — `test_login_rate_limit`
- [x] webhook signatures verified (X-Hub-Signature-256), replays ignored
- [x] uploads: CSV only, 2 MB max, parsed in memory, never served back
- [x] no user data in logs: Docker runs uvicorn with `--no-access-log` (search URLs can hold phones)
- [x] security headers: CSP (no inline scripts), X-Frame-Options DENY, nosniff, same-origin referrer
- [x] dependencies audited: `pip-audit -r requirements.txt` → no known vulnerabilities (2026-10-22)
- [x] privacy page (`/privacy`) lists processors: host, Google Gemini, Meta WhatsApp
