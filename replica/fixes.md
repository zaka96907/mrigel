# Fixes and angle

## Sample size, stated plainly

14 public reviews from 2 sources (Trustpilot for eGrow, Shopify App Store for Confirmify and
CodVerify). All 14 are 5 stars, mostly from Moroccan, Egyptian and Pakistani stores. COD Rocket
has 2 one-word reviews; Sovor COD and RTOx have none. **The reviews contain no complaints, so they
cannot rank what users hate.** `feedback.md` shows this.

The lists below therefore rest on **market evidence** (pricing pages, feature pages, Algerian
industry articles, job ads), labelled per item. Treat them as a direction to test with real
Algerian merchants, not as proven demand. First thing to do after the MVP: interview 5 merchants.

## 1. What they hate (market evidence, not reviews)

1. **Paying in dollars.** eGrow is $59 / $99 / $199 a month in USD, AI billed per reply, Meta fees
   on top, no free trial. In Algeria only 2.8% of consumers hold a credit card.
   Evidence: https://www.egrow.com/en/pricing , https://algeriatech.news/?p=31873
2. **Returned parcels eat the margin.** Couriers charge 300-600 DZD per shipment whatever happens;
   RTO is 15-20% in big cities and over 30% in rural and southern wilayas.
   Evidence: https://algeriatech.news/?p=31058
3. **Confirming by hand is a full-time job.** Merchants hire "confirmateurs de commande".
   Evidence: https://emploitic.com/entreprises/kimland/offres-d-emploi/services/confirmateurtrice-de-commande-0da955604d5090ffb7e4cec9

## 2. What is missing

1. **Algerian Darija.** None of eGrow, COD Rocket, Confirmify, CodVerify, Sovor or RTOx mention
   Algerian Darija on their public pages (checked 2026-10-22). Buyers answer "wah", "ih", "sa7a",
   "mazal", "khalih", mixed French/Arabic, Arabizi.
2. **Not Shopify-only.** COD Rocket, Confirmify, CodVerify, Sovor, RTOx are Shopify apps. Many
   Algerian sellers take orders from Facebook/Instagram/TikTok into a sheet. (Hypothesis to verify
   with merchants; no public dataset found.)
3. **Algerian geography built in.** 69 wilayas since the 2025 reform (59-69 new), stop-desk vs home
   delivery, per-wilaya return rates. Evidence: https://www.tsa-algerie.com/algerie-voici-les-numeros-des-onze-nouvelles-wilayas/
4. **Delivery slot and partial advance.** Offering morning/afternoon delivery reduces "not home"
   returns by 30-40%; a 200-500 DZD advance on orders above 3,000 DZD brings returns to 5-8%.
   Evidence (vendor blog, unverified): https://dzbuild.com/blog/reduce-cod-return-rate-algeria

## 3. What is unsolved

- **Small Algerian sellers who cannot get or pay for the WhatsApp Business API.** eGrow needs the
  official API and passes Meta fees through. A seller with one phone and one confirmer has nothing
  built for them.

## 4. Fix plan

| # | build | size | skill | evidence |
| --- | --- | --- | --- | --- |
| 1 | Darija reply understanding: rules for common replies + LLM fallback, answers in Darija | M | replica-build / backend | missing #1 |
| 2 | Works with the merchant's own WhatsApp today: one-tap prefilled message (wa.me) in an agent queue; official Cloud API as an upgrade | M | replica-build / backend | hate #3, unsolved |
| 3 | Risk score per order with Algerian signals (phone format, wilaya RTO, repeat returner, duplicate, value) + blacklist | M | replica-build | hate #2 |
| 4 | Any intake: manual, CSV import, webhook API (not Shopify-only) | S | replica-build | missing #2 |
| 5 | Delivery slot question + optional advance for high-value orders in the confirmation script | S | replica-build | missing #4 |
| 6 | Money-saved dashboard in DZD + per-wilaya return rate | S | replica-build | hate #2 |
| 7 | Carrier export (Yalidine, ZR Express, Maystro, NOEST) as CSV; API adapters later | S | replica-build | missing #3 |
| 8 | Price in dinars, pay locally (BaridiMob / CCP / Edahabia) | S | replica-launch | hate #1 |

## 5. The angle

A. For Algerian sellers who pay for every parcel that comes back, **[app]** confirms each order in
   Darija on WhatsApp before it ships, priced in dinars.
   Evidence: hate #1-#2, missing #1 (market evidence, 4 sources).
B. For merchants whose confirmers spend the day calling, **[app]** lets one person confirm three
   times more orders, then hands the easy replies to AI.
   Evidence: hate #3, unsolved (2 sources).
C. For sellers who sell from Instagram and a spreadsheet, **[app]** gives them the confirmation and
   dispatch tools Shopify stores get.
   Evidence: missing #2 (hypothesis, 0 datasets).

**Recommended: A.** It names the money problem merchants already feel, and Darija + dinars is the
part foreign tools do not do.
