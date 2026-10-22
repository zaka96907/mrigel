"""Algerian specifics: the 69 wilayas, phone numbers, regional return-rate baselines."""

import re
import unicodedata

# (code, French name, Arabic name). 59-69 created by the 2025 territorial reform.
WILAYAS: list[tuple[int, str, str]] = [
    (1, "Adrar", "أدرار"), (2, "Chlef", "الشلف"), (3, "Laghouat", "الأغواط"),
    (4, "Oum El Bouaghi", "أم البواقي"), (5, "Batna", "باتنة"), (6, "Béjaïa", "بجاية"),
    (7, "Biskra", "بسكرة"), (8, "Béchar", "بشار"), (9, "Blida", "البليدة"),
    (10, "Bouira", "البويرة"), (11, "Tamanrasset", "تمنراست"), (12, "Tébessa", "تبسة"),
    (13, "Tlemcen", "تلمسان"), (14, "Tiaret", "تيارت"), (15, "Tizi Ouzou", "تيزي وزو"),
    (16, "Alger", "الجزائر"), (17, "Djelfa", "الجلفة"), (18, "Jijel", "جيجل"),
    (19, "Sétif", "سطيف"), (20, "Saïda", "سعيدة"), (21, "Skikda", "سكيكدة"),
    (22, "Sidi Bel Abbès", "سيدي بلعباس"), (23, "Annaba", "عنابة"), (24, "Guelma", "قالمة"),
    (25, "Constantine", "قسنطينة"), (26, "Médéa", "المدية"), (27, "Mostaganem", "مستغانم"),
    (28, "M'Sila", "المسيلة"), (29, "Mascara", "معسكر"), (30, "Ouargla", "ورقلة"),
    (31, "Oran", "وهران"), (32, "El Bayadh", "البيض"), (33, "Illizi", "إليزي"),
    (34, "Bordj Bou Arréridj", "برج بوعريريج"), (35, "Boumerdès", "بومرداس"), (36, "El Tarf", "الطارف"),
    (37, "Tindouf", "تندوف"), (38, "Tissemsilt", "تيسمسيلت"), (39, "El Oued", "الوادي"),
    (40, "Khenchela", "خنشلة"), (41, "Souk Ahras", "سوق أهراس"), (42, "Tipaza", "تيبازة"),
    (43, "Mila", "ميلة"), (44, "Aïn Defla", "عين الدفلى"), (45, "Naâma", "النعامة"),
    (46, "Aïn Témouchent", "عين تموشنت"), (47, "Ghardaïa", "غرداية"), (48, "Relizane", "غليزان"),
    (49, "Timimoun", "تيميمون"), (50, "Bordj Badji Mokhtar", "برج باجي مختار"),
    (51, "Ouled Djellal", "أولاد جلال"), (52, "Béni Abbès", "بني عباس"), (53, "In Salah", "عين صالح"),
    (54, "In Guezzam", "عين قزام"), (55, "Touggourt", "تقرت"), (56, "Djanet", "جانت"),
    (57, "El M'Ghair", "المغير"), (58, "El Meniaa", "المنيعة"), (59, "Aflou", "أفلو"),
    (60, "El Abiodh Sidi Cheikh", "الأبيض سيدي الشيخ"), (61, "El Aricha", "العريشة"),
    (62, "El Kantara", "القنطرة"), (63, "Barika", "بريكة"), (64, "Bou Saâda", "بوسعادة"),
    (65, "Bir El Ater", "بئر العاتر"), (66, "Ksar El Boukhari", "قصر البخاري"),
    (67, "Ksar Chellala", "قصر الشلالة"), (68, "Aïn Oussara", "عين وسارة"), (69, "Messaad", "مسعد"),
]
WILAYA_BY_CODE = {code: (fr, ar) for code, fr, ar in WILAYAS}

# Return-to-origin baselines (share of shipped parcels that come back), used only until a store
# has enough history of its own. Source: AlgeriaTech, May 2026 — 15-20% in Algiers/Oran/Constantine,
# secondary cities 5-10 points higher, above 30% in rural and southern wilayas.
_TIER1 = {16, 31, 25, 9, 35, 42}
_TIER2 = {2, 4, 5, 6, 10, 12, 13, 14, 15, 18, 19, 20, 21, 22, 23, 24, 26, 27, 28, 29, 34, 36, 38,
          40, 41, 43, 44, 46, 48}
BASELINE_RTO = {1: 0.18, 2: 0.25, 3: 0.32}


def wilaya_tier(code: int | None) -> int:
    if code in _TIER1:
        return 1
    if code in _TIER2:
        return 2
    return 3


def wilaya_label(code: int | None, lang: str = "ar") -> str:
    if not code or code not in WILAYA_BY_CODE:
        return "—"
    fr, ar = WILAYA_BY_CODE[code]
    return f"{ar if lang == 'ar' else fr} ({code:02d})"


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("’", "'").replace("-", " ")
    text = re.sub(r"[أإآ]", "ا", text)
    text = text.replace("ة", "ه").replace("ى", "ي")
    text = re.sub(r"\b(wilaya de|wilaya|de|d'|ولايه)\b", " ", text)  # ة is already folded to ه
    return re.sub(r"\s+", " ", text).strip()


_ALIASES = {
    "algiers": 16, "alger centre": 16, "dzair": 16, "djazair": 16, "bejaia": 6, "bougie": 6,
    "tizi": 15, "bba": 34, "bordj": 34, "sba": 22, "sidi bel abbes": 22, "qsentina": 25,
    "wahran": 31, "msila": 28, "m sila": 28, "oum el bouaghi": 4, "oeb": 4, "el meghaier": 57,
    "el mghair": 57, "menia": 58, "el menia": 58, "bou saada": 64, "boussaada": 64,
    "ain oussera": 68, "ain ouessara": 68, "ksar boukhari": 66, "ksar chellala": 67,
}
_LOOKUP: dict[str, int] = {}
for _code, _fr, _ar in WILAYAS:
    _LOOKUP[_fold(_fr)] = _code
    _LOOKUP[_fold(_ar)] = _code
for _alias, _code in _ALIASES.items():
    _LOOKUP[_fold(_alias)] = _code


def parse_wilaya(value) -> int | None:
    """Accept 16, '16', '16 - Alger', 'Alger', 'الجزائر', 'Algiers'."""
    if value is None:
        return None
    if isinstance(value, int):
        return value if value in WILAYA_BY_CODE else None
    text = str(value).strip()
    if not text:
        return None
    match = re.match(r"^\s*(\d{1,2})\b", text)
    if match:
        code = int(match.group(1))
        return code if code in WILAYA_BY_CODE else None
    folded = _fold(text)
    if folded in _LOOKUP:
        return _LOOKUP[folded]
    for name, code in _LOOKUP.items():
        if len(name) >= 4 and (folded.startswith(name) or name.startswith(folded)) and len(folded) >= 4:
            return code
    return None


_MOBILE = re.compile(r"^0[567]\d{8}$")
_FIXED = re.compile(r"^0[2-4]\d{7}$")


def normalize_phone(raw: str) -> tuple[str, bool]:
    """Return (display form 0XXXXXXXXX, is_mobile). Unknown formats are returned cleaned, False."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("00213"):
        digits = digits[5:]
    elif digits.startswith("213") and len(digits) >= 11:
        digits = digits[3:]
    if len(digits) == 9 and digits[0] in "567":
        digits = "0" + digits
    elif len(digits) == 8 and digits[0] in "234":
        digits = "0" + digits
    if _MOBILE.match(digits):
        return digits, True
    return digits, False


def is_landline(display: str) -> bool:
    return bool(_FIXED.match(display or ""))


def whatsapp_number(display: str) -> str:
    """0555123456 -> 213555123456 (the format wa.me and the Cloud API expect)."""
    return "213" + display[1:] if display.startswith("0") else display
