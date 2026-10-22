# Brand: Mrigel (مريڨل)

Angle (from fixes.md, option A): for Algerian sellers who pay for every parcel that comes back,
Mrigel confirms each order in Darija on WhatsApp before it ships, priced in dinars.

## Name

"Mrigel" is Algerian slang for "all good, sorted" (كلش مريڨل). It is what a confirmed order is.
Short, Algerian, easy to say in Arabic and French, no relation to any competitor's name.

20 candidates: Mrigel, Wakked, Akked, Sahh, Kolis, KolisSafe, Amana, Sanad, Mizan, Wasl, Tamo,
Wekka, Nedja, Bab, Zid, Taslim, Sellam, Rasi, Sahhel, Tawkid.
Cut to 5: Mrigel, Sanad, Wasl, Kolis, Sahh.
Rejected on screening: Wakked / Akked / Tawkid (too close to the Shopify app "Akeed" and the
WooCommerce plugin "Akkedli", both COD confirmation tools); Amana (a Moroccan carrier eGrow integrates).

| check | Mrigel | Sanad | Wasl | Kolis | Sahh |
| --- | --- | --- | --- | --- | --- |
| web "name + app/startup" | run 2026-10-22: no software product found | to run | to run | to run | to run |
| Algerian trademark (INAPI) | to run | to run | to run | to run | to run |
| WIPO Global Brand Database | to run | to run | to run | to run | to run |
| domain .com / .dz | to run | to run | to run | to run | to run |
| App Store / Play | to run | to run | to run | to run | to run |
| handles (Instagram, TikTok, Facebook, GitHub) | to run | to run | to run | to run | to run |

Screening checks, not legal clearance. Check INAPI before spending money on the name.

## Palette

"Slip and stamp": the cool grey-green paper of a delivery slip, post-ink teal for text and the
sidebar, and the violet ink of an Algerian rubber stamp as the accent. Kraft brown appears only in
illustrations (parcel tape). Revised on 2026-10-22: the first draft (cream + clay) matched a
common generated-design look, so it was dropped.
Light: bg #eef1f0, surface #ffffff, text/ink #10262e, accent (stamp violet) #5a2fb0, kraft #b7792a.
Dark: bg #0b1a1f, surface #12252c, text #e8f0ee, accent #b69cff.
Contrast: 24 pairs per theme, 0 AA failures (`contrast.py`).
The one bold element: a rotated violet stamp "مريڨل" printed on an order once it is confirmed.

## Logo brief

- Idea: a round rubber stamp with a check mark — "this order is sorted".
- Mark: symbol + wordmark; Latin "Mrigel" and Arabic "مريڨل" lockups.
- Works at 16 px (favicon: the stamp ring with the check) and 1024 px app icon on ink background.
- Deliverables: SVG, 1024x1024 icon (no transparency), favicon set, 1200x630 social image.
- Must not use WhatsApp's speech-bubble phone, nor any competitor's mark.

## Voice

Three words: **Algerian, not folksy** (Darija where buyers see it, clear Arabic/French for the
merchant) · **direct, not cold** · **money-minded, not salesy** (always show dinars).

Do / don't:
- Do: "3 طلبيات تستنى تأكيد" — Don't: "You have pending items in your workflow".
- Do: show "وفرت 12,400 دج" — Don't: "Great job! 🎉🎉".
- Do: write buyer messages in polite Darija — Don't: use Moroccan or Gulf dialect words.
- Do: one action per button ("أكد", "ألغِ") — Don't: "Submit".
- Do: say what went wrong and what to do — Don't: "An error occurred".

Ten most-seen strings (Arabic UI): see `app/i18n.py` (keys `hero_title`, `signup_cta`,
`orders_empty`, `queue_empty`, `btn_confirm`, `btn_cancel`, `btn_whatsapp`, `saved_money`,
`import_done`, `error_generic`).
