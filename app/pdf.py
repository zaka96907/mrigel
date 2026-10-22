"""Monthly statement as a PDF (bilingual Arabic / French), for the merchant's own books and tax return.

Arabic text is shaped (arabic-reshaper) and put in visual order (python-bidi) before drawing, and
drawn with IBM Plex Sans Arabic (OFL), which also covers Latin.
"""

import io
from pathlib import Path

FONT_DIR = Path(__file__).parent / "pdf_fonts"
_registered = False


def _fonts() -> None:
    global _registered
    if _registered:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pdfmetrics.registerFont(TTFont("Plex", str(FONT_DIR / "IBMPlexSansArabic-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Plex-Bold", str(FONT_DIR / "IBMPlexSansArabic-Bold.ttf")))
    _registered = True


def ar(text: str) -> str:
    import arabic_reshaper
    from bidi import get_display

    return get_display(arabic_reshaper.reshape(str(text)))


def money(value: int) -> str:
    return f"{int(value or 0):,}".replace(",", " ") + " DA"


def monthly_statement(store_name: str, figures: dict) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    _fonts()
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    left, right = 48, width - 48
    pdf.setTitle(f"Mrigel - {store_name} - {figures['month']}")

    pdf.setFillColorRGB(0.35, 0.18, 0.69)
    pdf.rect(0, height - 92, width, 92, stroke=0, fill=1)
    pdf.setFillColorRGB(1, 1, 1)
    pdf.setFont("Plex-Bold", 20)
    pdf.drawString(left, height - 50, "Relevé mensuel")
    pdf.drawRightString(right, height - 50, ar("الكشف الشهري"))
    pdf.setFont("Plex", 11)
    pdf.drawString(left, height - 72, f"{store_name}  ·  {figures['month']}")
    pdf.drawRightString(right, height - 72, "Mrigel")

    rows = [
        ("Commandes reçues", "الطلبيات الواصلة", str(figures["orders"])),
        ("Commandes confirmées", "الطلبيات المؤكدة", str(figures["confirmed"])),
        ("Colis livrés", "الطرود المسلّمة", str(figures["delivered_n"])),
        ("Chiffre d'affaires livré", "رقم الأعمال المسلّم", money(figures["delivered_dzd"])),
        ("Colis retournés", "الطرود الراجعة", str(figures["returned_n"])),
        ("Coût estimé des retours", "تكلفة الرجوع التقديرية", money(figures["returns_cost_dzd"])),
        ("Encaissé par les transporteurs", "المبلغ المحصّل من شركات التوصيل", money(figures["collected_dzd"])),
        ("Frais des transporteurs", "رسوم شركات التوصيل", money(figures["fees_dzd"])),
        ("Net reçu", "الصافي", money(figures["collected_dzd"] - figures["fees_dzd"])),
    ]
    y = height - 130
    pdf.setFillColorRGB(0.1, 0.1, 0.12)
    for index, (fr, arabic, value) in enumerate(rows):
        if index % 2 == 0:
            pdf.setFillColorRGB(0.96, 0.95, 0.93)
            pdf.rect(left - 8, y - 8, right - left + 16, 26, stroke=0, fill=1)
            pdf.setFillColorRGB(0.1, 0.1, 0.12)
        bold = index == len(rows) - 1
        pdf.setFont("Plex-Bold" if bold else "Plex", 11)
        pdf.drawString(left, y, fr)
        pdf.drawRightString(right, y, ar(arabic))
        pdf.setFont("Plex-Bold", 11)
        pdf.drawCentredString(width / 2 + 20, y, value)
        y -= 28

    y -= 16
    pdf.setFont("Plex-Bold", 12)
    pdf.drawString(left, y, "Livraisons par jour")
    pdf.drawRightString(right, y, ar("التسليمات حسب اليوم"))
    y -= 22
    pdf.setFont("Plex", 10)
    for day, row in figures["by_day"]:
        if y < 70:
            pdf.showPage()
            pdf.setFont("Plex", 10)
            y = height - 60
        pdf.drawString(left, y, day)
        pdf.drawCentredString(width / 2, y, str(row["n"]))
        pdf.drawRightString(right, y, money(row["dzd"]))
        y -= 16
    if not figures["by_day"]:
        pdf.drawString(left, y, "—")

    pdf.setFont("Plex", 8)
    pdf.setFillColorRGB(0.4, 0.4, 0.45)
    pdf.drawString(left, 36, "Document généré par Mrigel à partir des commandes du magasin. Ce n'est pas une facture fiscale.")
    pdf.drawRightString(right, 24, ar("وثيقة من مريڨل محسوبة من طلبيات المتجر، ماشي فاتورة جبائية."))
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
