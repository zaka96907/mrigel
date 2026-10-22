import pytest

from app.algeria import WILAYAS, normalize_phone, parse_wilaya, whatsapp_number


@pytest.mark.parametrize("raw,expected,mobile", [
    ("0555123456", "0555123456", True),
    ("0555 12 34 56", "0555123456", True),
    ("+213 555 12 34 56", "0555123456", True),
    ("00213555123456", "0555123456", True),
    ("213661234567", "0661234567", True),
    ("771234567", "0771234567", True),
    ("021 45 67 89", "021456789", False),
    ("12345", "12345", False),
    ("", "", False),
])
def test_phone_formats(raw, expected, mobile):
    assert normalize_phone(raw) == (expected, mobile)


def test_whatsapp_number():
    assert whatsapp_number("0555123456") == "213555123456"


def test_69_wilayas_unique():
    codes = [c for c, _, _ in WILAYAS]
    assert codes == list(range(1, 70))


@pytest.mark.parametrize("value,code", [
    (16, 16), ("16", 16), ("16 - Alger", 16), ("Alger", 16), ("الجزائر", 16), ("Algiers", 16),
    ("Sétif", 19), ("setif", 19), ("سطيف", 19), ("Bejaia", 6), ("Bougie", 6), ("bba", 34),
    ("Bou Saâda", 64), ("Messaad", 69), ("Tizi Ouzou", 15), ("ولاية وهران", 31),
    ("", None), ("Paris", None), (99, None), ("00", None),
])
def test_parse_wilaya(value, code):
    assert parse_wilaya(value) == code
