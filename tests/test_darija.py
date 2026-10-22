import pytest

from app.darija import read_rules

CASES = [
    ("wah", "confirm"),
    ("Waaaah akid", "confirm"),
    ("واه", "confirm"),
    ("ايه بعتوها", "confirm"),
    ("1", "confirm"),
    ("Oui je confirme la commande", "confirm"),
    ("ok sahit", "confirm"),
    ("👍", "confirm"),
    ("la", "cancel"),
    ("لا ما نحبش", "cancel"),
    ("2", "cancel"),
    ("non merci", "cancel"),
    ("ma nconfirmich", "cancel"),
    ("مانحبش خلاص", "cancel"),
    ("batel", "cancel"),
    ("ghodwa", "postpone"),
    ("rani msafer, mba3d", "postpone"),
    ("غدوة إن شاء الله", "postpone"),
    ("wah bssah beddel l'adresse", "change_address"),
    ("wa9tach twasel?", "question"),
    ("شحال التوصيل لسطيف؟", "question"),
    ("sbah", "confirm"),
    ("", "unclear"),
    ("hmm", "unclear"),
]


@pytest.mark.parametrize("text,intent", CASES)
def test_intents(text, intent):
    assert read_rules(text).intent == intent


def test_slot_detected():
    reading = read_rules("wah, f sbah")
    assert reading.intent == "confirm"
    assert reading.slot == "morning"


def test_french_article_la_is_not_a_refusal():
    assert read_rules("je veux la livraison demain svp").intent != "cancel"


def test_short_confirm_is_confident():
    assert read_rules("wah").confidence >= 0.9


class _Order:
    customer_name = "Amina Benali"
    total_dzd = 2900
    delivery_fee_dzd = 400


def test_answers_common_questions_without_ai():
    from app.darija import read_reply

    facts = {"delivery_eta": "48 ساعة"}
    when = read_reply("wa9tach twasel?", _Order(), "Shop", facts=facts)
    assert when.intent == "question" and "48 ساعة" in when.answer
    fee = read_reply("ch7al livraison?", _Order(), "Shop", facts=facts)
    assert "400" in fee.answer and "2 900" in fee.answer
    total = read_reply("شحال المجموع؟", _Order(), "Shop", facts=facts)
    assert "2 900" in total.answer
    other = read_reply("kayen couleur rouge?", _Order(), "Shop", facts=facts)
    assert "الفريق" in other.answer
