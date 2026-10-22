"""Understand buyer replies written in Algerian Darija (Arabic script, Arabizi, French mix)
and answer in Darija.

Rules handle the replies buyers send most ("wah", "ih", "1", "la", "ghodwa"...) instantly and
for free. Anything unclear goes to the LLM when a key is configured; otherwise it is left for
a human. Nothing is auto-confirmed on a low-confidence guess.
"""

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field

log = logging.getLogger("mrigel.darija")

INTENTS = ("confirm", "cancel", "postpone", "change_address", "question", "unclear")


@dataclass
class Reading:
    intent: str
    confidence: float
    slot: str = ""                 # morning | afternoon | ""
    answer: str = ""               # suggested Darija reply
    source: str = "rules"          # rules | ai
    signals: list[str] = field(default_factory=list)


_ARABIZI = str.maketrans({"3": "ع", "7": "ح", "9": "ق", "5": "خ", "2": "ء"})


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"[ً-ْـ]", "", text)          # tashkeel, tatweel
    text = re.sub(r"[أإآ]", "ا", text).replace("ى", "ي").replace("ة", "ه").replace("ڨ", "ق")
    text = text.lower()
    text = re.sub(r"(.)\1{2,}", r"\1\1", text)                  # "waaaah" -> "waah"
    return re.sub(r"\s+", " ", text).strip()


def _words(text: str) -> list[str]:
    return re.findall(r"[\w']+", text)


def _has(text: str, patterns: list[str]) -> list[str]:
    hits = []
    for pattern in patterns:
        if re.search(pattern, text):
            hits.append(pattern)
    return hits


# Word-bounded patterns. \b works for Latin; Arabic tokens are matched as whole words via (?<!\w)(?!\w).
def _w(word: str) -> str:
    return rf"(?<!\w){word}(?!\w)"


CONFIRM = [_w(w) for w in (
    "واه", "وه", "ايه", "اييه", "ايوه", "اي", "نعم", "اكيد", "صحيت", "مريقل", "مليح", "ماشي مشكل",
    "اكد", "اكدها", "نأكد", "نوكد", "وكدها", "بعتوها", "ابعتوها", "جيبوها",
    "wah", "waah", "wa", "ih", "iih", "iyeh", "iyeh", "ey", "eyh", "aywa", "naam", "na3am", "akid", "akked",
    "mrigel", "mriguel", "sahit", "sa7it", "sahhit", "ok", "okay", "oki", "okk", "dac", "oui", "ouii", "yes",
    "d'accord", "daccord", "confirme", "confirmé", "confirmer", "je confirme", "nconfirmi", "nkonfirmi",
    "bla mochkil", "machi mochkil", "b3atha", "ab3atha", "jibouha",
)] + [r"^\s*1\s*$", r"^\s*1\W", "✅", "👍", "👌"]

CANCEL = [_w(w) for w in (
    "لا", "لالا", "ما نحبش", "مانحبش", "ما حبيتش", "ماحبيتش", "بطلت", "بطلها", "الغي", "الغيها", "لغيها",
    "بدلت رايي", "ماراهيش", "ماعنديش", "ما عنديش", "ماكانش", "خلاص لا", "ما بقيتش", "مابقيتش",
    "la", "lala", "lla", "non", "nn", "no", "annule", "annulé", "annuler", "batel", "batelha", "baTel",
    "ma7abitch", "mahabitch", "ma n7abch", "manhabch", "ma nhabch", "mabghitch", "ma bghitch",
    "khlas la", "ma b9itch", "mab9itch", "pas besoin", "j'annule",
)] + [r"^\s*2\s*$", r"^\s*2\W", "❌", "👎", r"(?<!\w)ma\s?\w+ch(?!\w)", r"(?<!\w)ما\s?\w+ش(?!\w)"]

POSTPONE = [_w(w) for w in (
    "غدوه", "غدا", "من بعد", "مبعد", "مازال", "ماززال", "الاسبوع الجاي", "السمانه الجايه", "نعيطلكم",
    "ghodwa", "ghedwa", "ghdwa", "mba3d", "mb3d", "men ba3d", "mazal", "mazel", "demain", "plus tard",
    "apres", "après", "semaine prochaine", "la semaine prochaine", "rani msafer", "rani barra",
    "مسافر", "راني برا", "راني خدام",
)]

ADDRESS = [_w(w) for w in (
    "العنوان", "عنوان", "بدلت الدار", "دار جديده", "adresse", "l'adresse", "address", "beddel", "bedel",
    "badel", "changer", "nouvelle adresse", "stop desk", "stopdesk", "bureau",
)]

QUESTION = [r"\?", r"؟"] + [_w(w) for w in (
    "وقتاش", "شحال", "قداش", "كاين", "واش", "كيفاش", "وين", "علاه", "التوصيل", "اللون", "المقاس", "الطايل",
    "wa9tach", "wqtach", "waktach", "ch7al", "chhal", "9adach", "qadach", "kayen", "wach", "kifach", "win",
    "3lah", "combien", "quand", "livraison", "couleur", "taille", "pointure",
)]

MORNING = [_w(w) for w in ("الصباح", "صباح", "الصبح", "sbah", "sba7", "matin", "le matin", "sbe7")]
AFTERNOON = [_w(w) for w in ("العشيه", "عشيه", "المساء", "3chiya", "achiya", "l'aprem", "aprem",
                                   "après-midi", "apres-midi", "soir", "le soir", "laachiya")]


def read_rules(text: str) -> Reading:
    norm = normalize(text)
    if not norm:
        return Reading("unclear", 0.0)
    tokens = _words(norm)
    confirm = _has(norm, CONFIRM)
    cancel = _has(norm, CANCEL)
    postpone = _has(norm, POSTPONE)
    address = _has(norm, ADDRESS)
    question = _has(norm, QUESTION)
    slot = "morning" if _has(norm, MORNING) else "afternoon" if _has(norm, AFTERNOON) else ""

    # "la" is also a French article: only count it as a refusal when the message is short
    # or starts with it.
    if cancel and all(p in (_w("la"), _w("no")) for p in cancel):
        if len(tokens) > 3 and not re.match(r"^(la|no)\b", norm):
            cancel = []
    # A negated confirm ("ma nconfirmich") is a refusal, not a confirmation.
    if cancel and confirm and any("ch(?!" in p or "ش(?!" in p for p in cancel):
        confirm = []

    signals = [s for s, hits in (("confirm", confirm), ("cancel", cancel), ("postpone", postpone),
                                 ("address", address), ("question", question)) if hits]

    if confirm and not cancel:
        if address:
            return Reading("change_address", 0.7, slot, signals=signals)
        if postpone:
            return Reading("postpone", 0.65, slot, signals=signals)
        confidence = 0.95 if len(tokens) <= 4 else 0.8
        if question:
            confidence = 0.6
        return Reading("confirm", confidence, slot, signals=signals)
    if cancel and not confirm:
        return Reading("cancel", 0.9 if len(tokens) <= 5 else 0.75, slot, signals=signals)
    if postpone and not cancel:
        return Reading("postpone", 0.75, slot, signals=signals)
    if address:
        return Reading("change_address", 0.7, slot, signals=signals)
    if question:
        return Reading("question", 0.7, slot, signals=signals)
    if slot:
        # "sbah" alone, in reply to "morning or afternoon?" after a confirmation
        return Reading("confirm", 0.6, slot, signals=["slot"])
    return Reading("unclear", 0.2, slot, signals=signals)


# ---------- replies ----------

SLOT_WORDS = {"morning": "الصباح", "afternoon": "العشية"}


WHEN = [_w(w) for w in ("وقتاش", "امتى", "شحال من يوم", "قداش من يوم", "wa9tach", "wqtach", "waktach", "imta",
                         "quand", "delai", "délai", "combien de jours", "ch7al men nhar", "chhal men nhar")]
PRICE = [_w(w) for w in ("شحال", "قداش", "بشحال", "السعر", "ch7al", "chhal", "9adach", "qadach", "b ch7al",
                          "combien", "prix", "price")]
SHIPPING = [_w(w) for w in ("التوصيل", "الليفريزون", "livraison", "liv", "frais", "توصيل")]
DESK = [_w(w) for w in ("ستوب ديسك", "المكتب", "stop desk", "stopdesk", "bureau", "agence")]


def _fmt(value: int) -> str:
    return f"{int(value or 0):,}".replace(",", " ")


def answer_question(text: str, order, facts: dict) -> str:
    """Answer the questions buyers ask most, from the order itself. Empty when it cannot."""
    norm = normalize(text)
    first = (order.customer_name or "").split(" ")[0]
    if _has(norm, WHEN):
        eta = facts.get("delivery_eta") or "24 إلى 72 ساعة"
        return f"مرحبا {first}، التوصيل ياخذ عادة {eta} من نهار التأكيد. أكّدلنا الطلبية (1) باش نبعتوها اليوم 🙏"
    if _has(norm, PRICE) and _has(norm, SHIPPING):
        fee = order.delivery_fee_dzd
        if fee:
            return f"التوصيل {_fmt(fee)} دج، والمجموع كامل {_fmt(order.total_dzd)} دج تخلّصو كي تستلم. نأكدوها؟ (1 نعم / 2 لا)"
        return f"المجموع كامل {_fmt(order.total_dzd)} دج تخلّصو كي تستلم. نأكدوها؟ (1 نعم / 2 لا)"
    if _has(norm, PRICE):
        return f"المجموع {_fmt(order.total_dzd)} دج، تخلّصو كي تستلم الكولي. نأكدوها؟ (1 نعم / 2 لا)"
    if _has(norm, DESK):
        return "إيه تقدر تستلم من ستوب ديسك (مكتب شركة التوصيل). قولنا البلدية باش نبدلو نوع التوصيل."
    return ""


def reply_for(reading: Reading, order, store_name: str, facts: dict | None = None, text: str = "") -> str:
    facts = facts or {}
    first = (order.customer_name or "").split(" ")[0]
    if reading.intent == "confirm":
        slot = f"، والتوصيل يكون {SLOT_WORDS[reading.slot]}" if reading.slot else ""
        return (f"صحيت {first}! ✅ طلبيتك تأكدت وراح تخرج قريب{slot}. "
                f"كي يعيطلك الليفرور ردّ عليه من فضلك. يعطيك الصحة 🙏")
    if reading.intent == "cancel":
        return f"مفهوم {first}، ألغينا الطلبية. إذا بدلت رايك راسلنا وقتما حبيت 🙏"
    if reading.intent == "postpone":
        return f"ماشي مشكل {first}، نعاودو نكلموك من بعد. قولنا الوقت اللي يناسبك 👍"
    if reading.intent == "change_address":
        return "مليح، عطينا العنوان الجديد كامل (البلدية والحي) ولا قولنا إذا تحب ستوب ديسك، باش نبدلوه."
    if reading.intent == "question":
        return answer_question(text, order, facts) or f"سؤال مليح {first}، واحد من الفريق ({store_name}) راح يجاوبك دقيقة."
    return f"سمحلنا {first} ما فهمناش مليح 🙏 ابعتلنا 1 باش تأكد الطلبية ولا 2 باش تلغيها."


# ---------- AI fallback ----------

_AI_PROMPT = """You read WhatsApp replies from Algerian buyers to a cash-on-delivery order confirmation.
Buyers write in Algerian Darija (Arabic script or Arabizi with digits like 3, 7, 9), French, or a mix.

Order: {order}
Store: {store}
Buyer reply: {text}

Return JSON only, with keys:
- intent: one of confirm, cancel, postpone, change_address, question, unclear
- confidence: 0 to 1 (be strict; under 0.7 if there is any doubt)
- slot: "morning", "afternoon" or ""
- answer: a short, polite reply in Algerian Darija (Arabic script) that a store employee could send.
  Answer the question if the order info allows; never invent prices, dates or policies not given.
"""


def read_ai(text: str, order, store_name: str, api_key: str, model: str, facts: dict | None = None) -> Reading | None:
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=8000))
        order_info = {
            "items": order.items, "total_dzd": order.total_dzd, "delivery_fee_dzd": order.delivery_fee_dzd,
            "wilaya_code": order.wilaya_code, "delivery_type": order.delivery_type, "stage": order.stage,
            "usual_delivery_time": (facts or {}).get("delivery_eta", ""),
        }
        response = client.models.generate_content(
            model=model,
            contents=_AI_PROMPT.format(order=json.dumps(order_info, ensure_ascii=False),
                                       store=store_name, text=text),
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
        )
        data = json.loads(response.text or "{}")
        intent = data.get("intent", "unclear")
        if intent not in INTENTS:
            intent = "unclear"
        slot = data.get("slot", "")
        return Reading(
            intent=intent,
            confidence=float(data.get("confidence", 0.5)),
            slot=slot if slot in ("morning", "afternoon") else "",
            answer=str(data.get("answer", ""))[:600],
            source="ai",
        )
    except Exception as exc:  # network, quota, bad JSON: fall back to rules, never crash a page
        log.warning("AI reading failed: %s", exc)
        return None


def read_reply(text: str, order, store_name: str, api_key: str = "", model: str = "",
               facts: dict | None = None) -> Reading:
    reading = read_rules(text)
    # a question the rules can answer from the order needs no AI
    known_answer = answer_question(text, order, facts or {}) if reading.intent == "question" else ""
    if reading.confidence < 0.7 and api_key and not known_answer:
        ai = read_ai(text, order, store_name, api_key, model, facts or {})
        if ai and ai.confidence >= reading.confidence:
            if not ai.answer:
                ai.answer = reply_for(ai, order, store_name, facts, text)
            return ai
    reading.answer = reply_for(reading, order, store_name, facts, text)
    return reading
