"""Back up a store to one ZIP file and restore it into a new, empty store.

Why: on a free host the database can be wiped (Render deletes free Postgres databases after their
trial). The owner downloads a backup, and after the database is recreated signs up again and
restores it. The ZIP also holds plain CSV files (orders, products, contacts) for Excel.

Every row gets a new id on restore and links between rows are rewritten, so a backup can also be
restored next to the original store without clashes. Team accounts are not in the backup (they
hold password hashes): the owner adds the team again. Secret settings (API tokens, webhook
secrets) are left out too; they are encrypted with this server's key and would not open elsewhere.
"""

import csv
import io
import json
import secrets
import uuid
import zipfile
from datetime import datetime

from sqlalchemy import DateTime, func, select

from .models import (BlacklistEntry, Campaign, Cart, Contact, Message, Order, OrderEvent, Payout, Product, Rule,
                     StockMove, Store, utcnow)
from .store_settings import SECRET_KEYS

VERSION = 1
# insertion order: a table only points to tables above it (products point to themselves: second pass)
MODELS = [Product, Payout, Order, OrderEvent, Contact, Message, BlacklistEntry, StockMove, Rule, Campaign, Cart]
MAX_BYTES = 40 * 1024 * 1024


class BackupError(Exception):
    pass


def _value(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _rows(db, model, store_id: str) -> list[dict]:
    columns = model.__table__.columns
    return [{c.name: _value(getattr(row, c.key)) for c in columns}
            for row in db.scalars(select(model).where(model.store_id == store_id))]


def export_zip(db, store: Store) -> bytes:
    data = {"mrigel_backup": VERSION, "exported_at": utcnow().isoformat(), "store_name": store.name,
            "settings": {k: v for k, v in (store.settings or {}).items() if k not in SECRET_KEYS and k != "demo"},
            "tables": {m.__tablename__: _rows(db, m, store.id) for m in MODELS}}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("backup.json", json.dumps(data, ensure_ascii=False))
        archive.writestr("orders.csv", _csv(
            ["id", "created_at", "customer_name", "phone", "wilaya_code", "commune", "address", "items", "total_dzd",
             "stage", "carrier", "tracking", "source", "paid_at", "cod_collected_dzd"],
            [{**o, "items": " + ".join(f"{i.get('qty', 1)}x {i.get('name', '')}" for i in (o.get("items") or []))}
             for o in data["tables"]["orders"]]))
        archive.writestr("products.csv", _csv(["sku", "name", "price_dzd", "cost_dzd", "stock", "active"],
                                              data["tables"]["products"]))
        archive.writestr("contacts.csv", _csv(["channel", "handle", "name", "opted_out", "last_message_at"],
                                              data["tables"]["contacts"]))
    return buffer.getvalue()


def _csv(fields: list[str], rows: list[dict]) -> str:
    out = io.StringIO()
    out.write("﻿")  # Excel opens UTF-8 Arabic correctly with a BOM
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def read_backup(raw: bytes) -> dict:
    if len(raw) > MAX_BYTES:
        raise BackupError("too_big")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            data = json.loads(archive.read("backup.json"))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise BackupError("bad_file") from exc
    if not isinstance(data, dict) or data.get("mrigel_backup") != VERSION or not isinstance(data.get("tables"), dict):
        raise BackupError("bad_file")
    return data


def store_is_empty(db, store: Store) -> bool:
    return not any(db.scalar(select(func.count()).select_from(m).where(m.store_id == store.id)) for m in (Order, Product))


def restore(db, store: Store, data: dict) -> dict:
    """Load a backup into an empty store. Returns {table: rows restored}."""
    if not store_is_empty(db, store):
        raise BackupError("not_empty")
    tables = data["tables"]
    new_ids: dict[str, str] = {}
    for model in MODELS:
        for row in tables.get(model.__tablename__) or []:
            if isinstance(row, dict) and row.get("id"):
                new_ids[str(row["id"])] = str(uuid.uuid4())
    counts, upsells = {}, []
    for model in MODELS:
        columns = {c.name: c for c in model.__table__.columns}
        count = 0
        for row in tables.get(model.__tablename__) or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            values = {}
            for name, column in columns.items():
                if name not in row:
                    continue
                value = row[name]
                target = next(iter(column.foreign_keys)).column.table.name if column.foreign_keys else None
                if name == "id":
                    value = new_ids[str(value)]
                elif target == "stores":
                    value = store.id
                elif target == "users":
                    value = None  # team members are not in the backup
                elif target and value is not None:
                    value = new_ids.get(str(value))
                    if value is None and not column.nullable:
                        break  # points to a row that is not in the file: skip this row
                elif isinstance(column.type, DateTime) and isinstance(value, str):
                    value = datetime.fromisoformat(value)
                values[column.key] = value
            else:
                if model is Product and values.get("upsell_product_id"):
                    upsells.append((values["id"], values.pop("upsell_product_id")))
                if model is Cart:
                    values["token"] = secrets.token_urlsafe(24)  # form links of the old site are dead anyway
                db.add(model(**values))
                count += 1
        db.flush()
        counts[model.__tablename__] = count
    for product_id, upsell_id in upsells:
        db.get(Product, product_id).upsell_product_id = upsell_id
    settings = {k: v for k, v in (data.get("settings") or {}).items() if k not in SECRET_KEYS and k != "demo"}
    store.settings = {**(store.settings or {}), **settings}
    if settings.get("dm_reply_product"):
        store.settings = {**store.settings, "dm_reply_product": new_ids.get(settings["dm_reply_product"], "")}
    return counts
