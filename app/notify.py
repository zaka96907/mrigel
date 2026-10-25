"""Messages Mrigel sends that are not the confirmation itself: delivery updates to the buyer, rule
messages, campaign messages and cart recovery.

Every message is a Message row first. In cloud mode it is queued and the job sends it; in assisted
mode it waits as "todo" and the agent sends it with one tap (wa.me), like the confirmation.
"""

import logging
from datetime import timedelta

from sqlalchemy import select

from . import whatsapp
from .algeria import normalize_phone
from .carriers import CARRIERS
from .models import Contact, Message, Order, Product, Store, utcnow
from .store_settings import get_settings

log = logging.getLogger("mrigel.notify")

STAGE_NOTICES = {"shipped": "tpl_shipped", "delivered": "tpl_delivered"}


def _fmt(value: int) -> str:
    return f"{int(value or 0):,}".replace(",", " ")


def render_text(template: str, order: Order | None, store: Store, **extra) -> str:
    values = {"name": "", "store": store.name, "total": "", "carrier": "", "tracking": "", "items": "", "link": ""}
    if order is not None:
        carrier = CARRIERS.get(order.carrier or "", "")
        values.update({
            "name": (order.customer_name or "").split(" ")[0],
            "total": _fmt(order.total_dzd),
            "carrier": carrier,
            "tracking": order.tracking or "",
            "items": order.items_label or "",
        })
    values.update({k: str(v) for k, v in extra.items()})
    try:
        return template.format(**values).strip()
    except (KeyError, IndexError, ValueError):
        return template.strip()


def contact_for(db, store_id: str, channel: str, handle: str, name: str = "") -> Contact:
    contact = db.scalar(select(Contact).where(Contact.store_id == store_id, Contact.channel == channel,
                                              Contact.handle == handle))
    if contact is None:
        contact = Contact(store_id=store_id, channel=channel, handle=handle, name=name[:120])
        db.add(contact)
        db.flush()
    elif name and not contact.name:
        contact.name = name[:120]
    return contact


def whatsapp_contact(db, order: Order) -> Contact:
    return contact_for(db, order.store_id, "whatsapp", order.phone, order.customer_name)


def touch(contact: Contact, inbound: bool) -> None:
    now = utcnow()
    contact.last_message_at = now
    if inbound:
        contact.last_inbound_at = now
        contact.unread = (contact.unread or 0) + 1


def _queue(db, store: Store, order: Order | None, contact: Contact, text: str, kind: str) -> Message | None:
    if contact.opted_out and kind in ("campaign", "recovery"):
        return None
    cloud = get_settings(store).get("whatsapp_mode") == "cloud" and not (store.settings or {}).get("demo")
    message = Message(store_id=store.id, order_id=order.id if order else None, contact_id=contact.id, kind=kind,
                      direction="out", text=text[:4000], status="queued" if cloud else "todo")
    db.add(message)
    touch(contact, inbound=False)
    if order is not None:
        from .services import add_event

        add_event(db, order, "whatsapp", text[:140], direction="out", status=message.status, msg_kind=kind)
    return message


def queue_text(db, order: Order, template: str, kind: str = "notify") -> Message | None:
    store = db.get(Store, order.store_id)
    if not order.phone_valid:
        return None
    return _queue(db, store, order, whatsapp_contact(db, order), render_text(template, order, store), kind)


def queue_to_phone(db, store: Store, phone: str, name: str, text: str, kind: str) -> Message | None:
    display, valid = normalize_phone(phone)
    if not valid:
        return None
    return _queue(db, store, None, contact_for(db, store.id, "whatsapp", display, name), text, kind)


def on_stage(db, order: Order, stage: str) -> None:
    """Called by set_stage: tell the buyer when the parcel leaves and when it is delivered."""
    store = db.get(Store, order.store_id)
    cfg = get_settings(store)
    key = STAGE_NOTICES.get(stage)
    if key and cfg.get("notify_" + stage):
        queue_text(db, order, cfg.get(key, ""), kind="notify")


def out_for_delivery(db, order: Order, user_id: str | None = None) -> Message | None:
    store = db.get(Store, order.store_id)
    message = queue_text(db, order, get_settings(store).get("tpl_out", ""), kind="notify")
    return message


def send_queued(db, limit: int = 200) -> dict:
    """Send cloud-mode messages waiting in the queue. Called by the job loop."""
    done = {"sent": 0, "failed": 0}
    stores: dict[str, Store] = {}
    queued = db.scalars(select(Message).where(Message.status == "queued", Message.direction == "out")
                        .order_by(Message.created_at).limit(limit)).all()
    for message in queued:
        store = stores.get(message.store_id) or db.get(Store, message.store_id)
        stores[message.store_id] = store
        contact = db.get(Contact, message.contact_id) if message.contact_id else None
        if not store or not contact:
            message.status = "failed"
            done["failed"] += 1
            continue
        try:
            message.provider_id = send_now(store, contact, message) or None
            message.status = "sent"
            done["sent"] += 1
        except whatsapp.CloudError as exc:
            log.info("queued message %s not sent: %s", message.id, exc)
            message.status = "failed"
            done["failed"] += 1
    return done


def send_now(store: Store, contact: Contact, message: Message) -> str:
    """Send through the right channel. WhatsApp outside the 24 h window needs an approved template."""
    from . import meta

    if contact.channel in ("messenger", "instagram"):
        return meta.send_text(store, contact.channel, contact.handle, message.text)
    cfg = get_settings(store)
    window_open = contact.last_inbound_at is not None and (
        (utcnow() - _utc(contact.last_inbound_at)).total_seconds() < 23.5 * 3600)
    template = cfg.get("wa_campaign_template") if message.kind == "campaign" else cfg.get("wa_notify_template")
    if not window_open and template:
        return whatsapp.cloud_send_named_template(store, contact.handle, template, [message.text[:1000]])
    return whatsapp.cloud_send_text(store, contact.handle, message.text)


def _utc(value):
    from .services import as_utc

    return as_utc(value)


# ---------------------------------------------------------------- automatic first answer

AUTO_REPLY_GAP = timedelta(hours=12)


def form_link(db, store: Store, base_url: str) -> str:
    """The order form to send: the chosen product, else the newest product with a form."""
    cfg = get_settings(store)
    product = None
    if cfg.get("dm_reply_product"):
        product = db.get(Product, cfg["dm_reply_product"])
        if product and (product.store_id != store.id or not product.active or not product.form_enabled):
            product = None
    if product is None:
        product = db.scalar(select(Product).where(Product.store_id == store.id, Product.active.is_(True),
                                                  Product.form_enabled.is_(True))
                            .order_by(Product.created_at.desc()).limit(1))
    return f"{base_url.rstrip('/')}/f/{product.id}" if product else ""


def dm_auto_reply(db, store: Store, contact: Contact, base_url: str) -> Message | None:
    """Answer a new message on its own: thanks + the order form link. At most once every 12 h per
    person, never to someone who said STOP, never in the demo. WhatsApp needs cloud mode (assisted
    mode has no way to send without a human)."""
    cfg = get_settings(store)
    if not cfg.get("dm_auto_reply") or contact.opted_out or (store.settings or {}).get("demo"):
        return None
    if contact.channel == "whatsapp" and cfg.get("whatsapp_mode") != "cloud":
        return None
    last = db.scalar(select(Message.created_at).where(Message.contact_id == contact.id, Message.kind == "auto")
                     .order_by(Message.created_at.desc()).limit(1))
    if last is not None and utcnow() - _utc(last) < AUTO_REPLY_GAP:
        return None
    text = render_text(cfg.get("tpl_dm_reply", ""), None, store, link=form_link(db, store, base_url),
                       name=(contact.name or "").split(" ")[0])
    if not text:
        return None
    message = Message(store_id=store.id, contact_id=contact.id, direction="out", text=text[:2000], kind="auto",
                      channel=contact.channel, status="queued")
    try:
        message.provider_id = send_now(store, contact, message) or None
        message.status = "sent"
    except whatsapp.CloudError as exc:
        log.info("auto reply to %s not sent: %s", contact.id, exc)
        message.status = "failed"
    db.add(message)
    touch(contact, inbound=False)
    return message
