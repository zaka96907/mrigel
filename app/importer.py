"""CSV import. Accepts Excel/Google Sheets exports in Arabic, French or English headers."""

import csv
import io
import re
import unicodedata

from sqlalchemy import select

from .models import Order
from .services import OrderError, create_order

HEADERS = {
    "external_id": ["id", "order id", "order_id", "reference", "référence", "ref", "n commande", "numero", "رقم الطلب", "رقم الطلبية"],
    "customer_name": ["name", "nom", "nom complet", "client", "customer", "full name", "الاسم", "الاسم الكامل", "الزبون", "اسم الزبون"],
    "phone": ["phone", "tel", "tél", "téléphone", "telephone", "mobile", "numéro", "الهاتف", "رقم الهاتف", "الرقم"],
    "wilaya": ["wilaya", "state", "province", "الولاية", "ولاية"],
    "commune": ["commune", "city", "ville", "baladia", "البلدية", "بلدية"],
    "address": ["address", "adresse", "العنوان", "عنوان"],
    "product": ["product", "produit", "article", "item", "المنتج", "السلعة", "المنتوج"],
    "sku": ["sku", "code produit", "code article", "رمز المنتج"],
    "qty": ["qty", "quantity", "quantité", "qte", "الكمية"],
    "total": ["total", "price", "prix", "montant", "amount", "المبلغ", "السعر", "المجموع"],
    "delivery_fee": ["delivery fee", "frais de livraison", "livraison", "shipping", "سعر التوصيل", "التوصيل"],
    "delivery_type": ["delivery type", "type de livraison", "stop desk", "stopdesk", "نوع التوصيل"],
    "note": ["note", "notes", "remarque", "commentaire", "ملاحظة", "ملاحظات"],
}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("_", " ").replace("-", " ").replace("ـ", "")
    return re.sub(r"\s+", " ", text).strip(" :")


_FOLDED = {field: [_fold(h) for h in names] for field, names in HEADERS.items()}


def map_columns(header: list[str]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    used: set[str] = set()
    for index, raw in enumerate(header):
        folded = _fold(raw)
        for field, names in _FOLDED.items():
            if field in used:
                continue
            if folded in names:
                mapping[index] = field
                used.add(field)
                break
    return mapping


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1256", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def import_csv(db, store, data: bytes, user_id: str | None = None, max_rows: int = 5000) -> dict:
    text = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    report = {"imported": 0, "duplicates": 0, "errors": [], "missing": [], "orders": []}
    if not rows:
        report["errors"].append({"row": 0, "key": "err_empty_file"})
        return report
    mapping = map_columns(rows[0])
    present = set(mapping.values())
    report["missing"] = [f for f in ("customer_name", "phone", "wilaya", "total") if f not in present]
    if "customer_name" not in present or "phone" not in present:
        report["errors"].append({"row": 1, "key": "err_columns"})
        return report

    for line_no, row in enumerate(rows[1:max_rows + 1], start=2):
        if not any(cell.strip() for cell in row):
            continue
        record = {field: row[index].strip() for index, field in mapping.items() if index < len(row)}
        if record.get("external_id"):
            exists = db.scalar(select(Order.id).where(Order.store_id == store.id,
                                                      Order.external_id == record["external_id"]))
            if exists:
                report["duplicates"] += 1
                continue
        try:
            with db.begin_nested():
                order = create_order(db, store, record, source="csv", user_id=user_id)
            report["imported"] += 1
            report["orders"].append(order.id)
        except OrderError as exc:
            report["errors"].append({"row": line_no, "key": str(exc)})
    return report


SAMPLE_CSV = (
    "رقم الطلب,الاسم,الهاتف,الولاية,البلدية,العنوان,المنتج,الكمية,المبلغ,سعر التوصيل,نوع التوصيل\n"
    "A-1001,أمينة بن علي,0555 12 34 56,16,باب الزوار,حي 5 جويلية,كريم مرطب,1,2500,400,home\n"
    "A-1002,Karim Haddad,+213 661 23 45 67,Sétif,El Eulma,Cité 300 logts,Montre classique,1,4800,600,stopdesk\n"
)
