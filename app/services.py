"""Order operations shared by the pages, the API, the webhook and the jobs."""

from datetime import datetime, timedelta

from sqlalchemy import case, select

from . import catalog, darija, notify, rules
from .algeria import normalize_phone, parse_wilaya
from .config import settings
from .models import BlacklistEntry, Message, Order, OrderEvent, Store, utcnow
from .risk import apply_risk
from .store_settings import get_settings

TRANSITIONS = {
    "new": {"pending", "confirmed", "cancelled", "postponed", "no_answer"},
    "pending": {"confirmed", "cancelled", "postponed", "no_answer", "new"},
    "postponed": {"pending", "confirmed", "cancelled", "no_answer", "new"},
    "no_answer": {"pending", "confirmed", "cancelled", "postponed", "new"},
    "confirmed": {"shipped", "cancelled", "pending"},
    "shipped": {"delivered", "returned"},
    "delivered": {"returned"},
    "returned": {"new"},
    "cancelled": {"new"},
}


class OrderError(ValueError):
    """Raised with an i18n key as message."""


def _int(value, default: int = 0) -> int:
    try:
        return max(0, int(float(str(value).replace(" ", "").replace(",", ".") or default)))
    except (TypeError, ValueError):
        return default


def clean_items(raw) -> list[dict]:
    items = []
    for item in raw or []:
        if isinstance(item, str):
            item = {"name": item}
        name = str(item.get("name") or item.get("product") or "").strip()[:120]
        if not name:
            continue
        clean = {"name": name, "qty": max(1, _int(item.get("qty") or item.get("quantity"), 1)),
                 "price_dzd": _int(item.get("price") or item.get("price_dzd"))}
        sku = str(item.get("sku") or "").strip()[:60]
        if sku:
            clean["sku"] = sku
        if item.get("product_id"):
            clean["product_id"] = str(item["product_id"])[:36]
        items.append(clean)
    return items


def create_order(db, store: Store, data: dict, source: str = "manual", user_id: str | None = None) -> Order:
    name = str(data.get("customer_name") or data.get("name") or "").strip()[:120]
    phone_raw = str(data.get("phone") or "").strip()
    if not name:
        raise OrderError("err_name_required")
    if not phone_raw:
        raise OrderError("err_phone_required")
    phone, valid = normalize_phone(phone_raw)
    items = clean_items(data.get("items"))
    if not items and data.get("product"):
        items = clean_items([{"name": data.get("product"), "qty": data.get("qty") or 1, "sku": data.get("sku") or ""}])
    items = catalog.link_items(db, store.id, items)
    total = _int(data.get("total") if data.get("total") not in (None, "") else data.get("total_dzd"))
    if not total and items:
        total = sum(i["qty"] * i["price_dzd"] for i in items)
    delivery_type = "stopdesk" if str(data.get("delivery_type", "")).lower() in {"stopdesk", "stop desk", "bureau", "desk", "مكتب"} else "home"
    external_id = str(data.get("external_id") or "").strip()[:80] or None

    order = Order(
        store_id=store.id,
        external_id=external_id,
        source=source,
        customer_name=name,
        phone=phone,
        phone_valid=valid,
        wilaya_code=parse_wilaya(data.get("wilaya") if data.get("wilaya") not in (None, "") else data.get("wilaya_code")),
        commune=str(data.get("commune") or "").strip()[:120],
        address=str(data.get("address") or "").strip()[:255],
        delivery_type=delivery_type,
        items=items,
        total_dzd=total,
        delivery_fee_dzd=_int(data.get("delivery_fee") or data.get("delivery_fee_dzd")),
        note=str(data.get("note") or "").strip()[:2000],
        created_at=data.get("created_at") or utcnow(),
    )
    db.add(order)
    db.flush()
    if data.get("tags"):
        order.tags = [str(t)[:30] for t in data["tags"]][:10]
    apply_risk(db, order)
    add_event(db, order, "created", source, user_id=user_id)
    rules.run(db, order, "order_created")
    from .storefront import mark_recovered

    mark_recovered(db, order)
    return order


def add_event(db, order: Order, kind: str, text: str = "", user_id: str | None = None, **data) -> OrderEvent:
    event = OrderEvent(store_id=order.store_id, order_id=order.id, kind=kind, text=text, user_id=user_id, data=data)
    db.add(event)
    return event


def set_stage(db, order: Order, stage: str, user_id: str | None = None, reason: str = "",
              blacklist: bool = False, postpone_hours: int = 0) -> None:
    if stage == order.stage:
        return
    if stage not in TRANSITIONS.get(order.stage, set()):
        raise OrderError("err_bad_transition")
    previous = order.stage
    order.stage = stage
    now = utcnow()
    if stage == "confirmed":
        order.confirmed_at = now
        order.confirmed_by_id = user_id
    elif stage == "shipped":
        order.shipped_at = now
    elif stage in ("delivered", "returned", "cancelled"):
        order.closed_at = now
    elif stage == "postponed":
        order.postponed_until = now + timedelta(hours=postpone_hours or 24)
    elif stage == "new":
        order.closed_at = None
    if stage == "cancelled":
        order.cancel_reason = reason[:60]
    add_event(db, order, "stage", reason, user_id=user_id, frm=previous, to=stage)
    if blacklist and stage in ("returned", "cancelled"):
        add_to_blacklist(db, order.store_id, order.phone, reason or stage, user_id)
    catalog.on_stage(db, order, previous, stage)
    notify.on_stage(db, order, stage)
    rules.run(db, order, "stage_changed")


def add_to_blacklist(db, store_id: str, phone_raw: str, reason: str = "", user_id: str | None = None) -> BlacklistEntry | None:
    phone, _ = normalize_phone(phone_raw)
    if not phone:
        return None
    existing = db.scalar(select(BlacklistEntry).where(BlacklistEntry.store_id == store_id, BlacklistEntry.phone == phone))
    if existing:
        return existing
    entry = BlacklistEntry(store_id=store_id, phone=phone, reason=reason[:200], created_by_id=user_id)
    db.add(entry)
    db.flush()
    # re-score open orders from this phone
    for order in db.scalars(select(Order).where(Order.store_id == store_id, Order.phone == phone,
                                                Order.stage.in_(("new", "pending", "postponed", "no_answer", "confirmed")))):
        apply_risk(db, order)
    return entry


def log_outbound(db, order: Order, text: str, user_id: str | None = None, provider_id: str | None = None,
                 status: str = "logged", ai: bool = False) -> Message:
    contact = notify.whatsapp_contact(db, order)
    message = Message(store_id=order.store_id, order_id=order.id, contact_id=contact.id, direction="out", text=text,
                      provider_id=provider_id, status=status, ai=ai)
    db.add(message)
    notify.touch(contact, inbound=False)
    order.attempts = (order.attempts or 0) + 1
    order.last_contact_at = utcnow()
    if order.stage in ("new", "no_answer", "postponed"):
        set_stage(db, order, "pending", user_id=user_id, reason="whatsapp")
    add_event(db, order, "whatsapp", text[:140], user_id=user_id, direction="out", status=status)
    return message


def read_buyer_reply(db, store: Store, order: Order, text: str, user_id: str | None = None,
                     provider_id: str | None = None) -> darija.Reading:
    cfg = get_settings(store)
    api_key = (cfg.get("gemini_api_key") or settings.gemini_api_key) if cfg.get("ai_enabled") else ""
    reading = darija.read_reply(text, order, store.name, api_key=api_key, model=settings.gemini_model,
                                facts={"delivery_eta": cfg.get("delivery_eta", "")})
    contact = notify.whatsapp_contact(db, order)
    db.add(Message(store_id=order.store_id, order_id=order.id, contact_id=contact.id, direction="in", text=text[:4000],
                   intent=reading.intent, provider_id=provider_id, status="received"))
    if provider_id:  # a real inbound message from the webhook opens the 24 h window
        notify.touch(contact, inbound=True)
    else:
        contact.last_message_at = utcnow()
    if reading.slot:
        order.preferred_slot = reading.slot
    add_event(db, order, "ai", reading.intent, user_id=user_id, confidence=round(reading.confidence, 2),
              source=reading.source, slot=reading.slot)
    return reading


AUTO_APPLY = {"confirm": "confirmed", "cancel": "cancelled", "postpone": "postponed"}


def apply_reading(db, order: Order, reading: darija.Reading, user_id: str | None = None) -> bool:
    """Move the order when the reading is confident enough. Returns True if it moved."""
    target = AUTO_APPLY.get(reading.intent)
    if not target or reading.confidence < 0.8 or target not in TRANSITIONS.get(order.stage, set()):
        return False
    set_stage(db, order, target, user_id=user_id, reason="buyer_reply" if target != "cancelled" else "buyer_no")
    return True


def next_in_queue(db, store_id: str, skip: list[str] | None = None) -> Order | None:
    now = utcnow()
    query = (
        select(Order)
        .where(Order.store_id == store_id,
               (Order.stage.in_(("new", "no_answer")))
               | ((Order.stage == "postponed") & (Order.postponed_until <= now)))
        .order_by(case((Order.stage == "new", 0), else_=1), Order.created_at.asc())
    )
    if skip:
        query = query.where(Order.id.not_in(skip))
    return db.scalars(query.limit(1)).first()


def queue_size(db, store_id: str) -> int:
    from sqlalchemy import func

    now = utcnow()
    return db.scalar(
        select(func.count()).select_from(Order).where(
            Order.store_id == store_id,
            (Order.stage.in_(("new", "no_answer"))) | ((Order.stage == "postponed") & (Order.postponed_until <= now)))
    ) or 0


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    from datetime import timezone

    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
