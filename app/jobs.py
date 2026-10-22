"""Follow-ups for buyers who have not answered. Runs every minute in-process, or via POST /tasks/run."""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select

from . import whatsapp
from .db import session_scope
from .models import Order, Store, utcnow
from .services import as_utc, log_outbound, set_stage
from .store_settings import get_settings

log = logging.getLogger("mrigel.jobs")

REMINDER = "{name}، سمحلنا على الإزعاج 🙏 مازلنا نستناو تأكيدك للطلبية. ابعتلنا 1 باش تأكد ولا 2 باش تلغي."


def run_followups() -> dict:
    done = {"reminded": 0, "no_answer": 0, "requeued": 0}
    now = utcnow()
    with session_scope() as db:
        stores = {s.id: s for s in db.scalars(select(Store))}
        pending = db.scalars(select(Order).where(Order.stage == "pending")).all()
        for order in pending:
            store = stores.get(order.store_id)
            if not store:
                continue
            cfg = get_settings(store)
            wait = timedelta(minutes=int(cfg.get("followup_minutes") or 120))
            last = as_utc(order.last_contact_at) or as_utc(order.created_at)
            if now - last < wait:
                continue
            # did the buyer answer since our last message?
            if any(m.direction == "in" and as_utc(m.created_at) >= last for m in order.messages):
                continue
            attempts = order.attempts or 0
            if cfg.get("whatsapp_mode") == "cloud" and attempts < int(cfg.get("max_attempts") or 3):
                text = REMINDER.format(name=(order.customer_name or "").split(" ")[0])
                try:
                    provider_id = whatsapp.cloud_send_text(store, order.phone, text)
                    log_outbound(db, order, text, provider_id=provider_id, status="sent")
                    done["reminded"] += 1
                    continue
                except whatsapp.CloudError as exc:
                    log.info("reminder not sent for %s: %s", order.id, exc)
            set_stage(db, order, "no_answer", reason="no_reply")
            done["no_answer"] += 1

        # postponed orders whose time has come go back to the queue on their own (see next_in_queue);
        # count them for the log.
        done["requeued"] = len([o for o in db.scalars(select(Order).where(Order.stage == "postponed"))
                                if as_utc(o.postponed_until) and as_utc(o.postponed_until) <= now])
    return done


async def loop(interval: int = 60) -> None:
    while True:
        try:
            result = await asyncio.to_thread(run_followups)
            if any(result.values()):
                log.info("follow-ups: %s", result)
        except Exception:  # keep the loop alive whatever happens
            log.exception("follow-up run failed")
        await asyncio.sleep(interval)
