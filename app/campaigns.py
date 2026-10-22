"""WhatsApp campaigns to past buyers (new collection, restock, Eid promo).

Audience: buyers whose orders reached the chosen stages (default: delivered), optionally limited to
some wilayas and a period; one message per phone; blacklisted numbers and people who answered
STOP are always left out.

Cloud mode sends through an approved marketing template (Meta's rule for business-initiated
messages). Assisted mode does not mass-send from a personal number: it gives the agent a list
with one tap per buyer, which is what WhatsApp allows.
"""

import re
from datetime import timedelta

from sqlalchemy import select

from . import notify
from .models import BlacklistEntry, Campaign, Contact, Order, Store, utcnow
from .store_settings import get_settings

STOP_WORDS = re.compile(r"^\s*(stop|stp|arr[eê]t|ستوب|وقف|بلا رسائل|ما تبعتوليش)\s*[.!]*\s*$", re.I)
MAX_RECIPIENTS = 2000


def is_stop(text: str) -> bool:
    return bool(STOP_WORDS.match(text or ""))


def audience(db, store: Store, stages: list[str], wilayas: list[int], days: int) -> list[dict]:
    query = select(Order).where(Order.store_id == store.id, Order.phone_valid.is_(True))
    if stages:
        query = query.where(Order.stage.in_(stages))
    if wilayas:
        query = query.where(Order.wilaya_code.in_(wilayas))
    if days:
        query = query.where(Order.created_at >= utcnow() - timedelta(days=days))
    blocked = set(db.scalars(select(BlacklistEntry.phone).where(BlacklistEntry.store_id == store.id)))
    blocked |= set(db.scalars(select(Contact.handle).where(Contact.store_id == store.id, Contact.channel == "whatsapp",
                                                           Contact.opted_out.is_(True))))
    seen: dict[str, dict] = {}
    for order in db.scalars(query.order_by(Order.created_at.desc())):
        if order.phone in blocked or order.phone in seen:
            continue
        seen[order.phone] = {"phone": order.phone, "name": order.customer_name, "status": "pending"}
        if len(seen) >= MAX_RECIPIENTS:
            break
    return list(seen.values())


def personal_text(campaign: Campaign, store: Store, recipient: dict) -> str:
    return notify.render_text(campaign.text, None, store, name=(recipient.get("name") or "").split(" ")[0])


def send_cloud(db, store: Store, campaign: Campaign) -> int:
    """Queue every pending recipient; the job sends them. Returns how many were queued."""
    if get_settings(store).get("whatsapp_mode") != "cloud":
        return 0
    queued = 0
    recipients = []
    for recipient in campaign.recipients or []:
        recipient = dict(recipient)
        if recipient.get("status") == "pending":
            message = notify.queue_to_phone(db, store, recipient["phone"], recipient.get("name", ""),
                                            personal_text(campaign, store, recipient), "campaign")
            recipient["status"] = "queued" if message else "skipped"
            queued += 1 if message else 0
        recipients.append(recipient)
    campaign.recipients = recipients
    campaign.status = "sending"
    return queued


def mark(campaign: Campaign, phone: str, status: str = "sent") -> bool:
    changed = False
    recipients = []
    for recipient in campaign.recipients or []:
        recipient = dict(recipient)
        if recipient.get("phone") == phone and recipient.get("status") == "pending":
            recipient["status"] = status
            changed = True
        recipients.append(recipient)
    campaign.recipients = recipients
    if all(r.get("status") != "pending" for r in recipients):
        campaign.status = "done"
    elif changed:
        campaign.status = "sending"
    return changed
