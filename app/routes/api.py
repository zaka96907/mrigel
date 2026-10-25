"""Machine endpoints: order intake API, WhatsApp Cloud webhook, cron."""

import hmac
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import campaigns, notify, whatsapp
from ..algeria import normalize_phone
from ..config import settings
from ..db import get_db
from ..jobs import run_followups
from ..models import Message, Order, Store
from ..ratelimit import limiter
from ..risk import level
from ..services import OrderError, apply_reading, create_order, log_outbound, read_buyer_reply
from ..store_settings import get_settings

router = APIRouter()
log = logging.getLogger("mrigel.api")


def _store_from_key(db: Session, key: str | None) -> Store:
    if not key:
        raise HTTPException(status_code=401, detail="missing X-Api-Key")
    store = db.scalar(select(Store).where(Store.api_key == key.strip()))
    if not store:
        raise HTTPException(status_code=401, detail="invalid X-Api-Key")
    return store


def _order_json(order: Order) -> dict:
    return {"id": order.id, "external_id": order.external_id, "stage": order.stage, "phone": order.phone,
            "phone_valid": order.phone_valid, "wilaya_code": order.wilaya_code, "total_dzd": order.total_dzd,
            "risk_score": order.risk_score, "risk_level": level(order.risk_score),
            "risk_reasons": [r.get("code") for r in order.risk_reasons or []]}


@router.post("/api/v1/orders", dependencies=[Depends(limiter("api", 120, 60))])
async def api_create_order(request: Request, x_api_key: str | None = Header(default=None),
                           db: Session = Depends(get_db)):
    store = _store_from_key(db, x_api_key)
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="body must be JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    external_id = str(payload.get("external_id") or "").strip()
    if external_id:
        existing = db.scalar(select(Order).where(Order.store_id == store.id, Order.external_id == external_id[:80]))
        if existing:
            return JSONResponse(_order_json(existing), status_code=200)
    try:
        order = create_order(db, store, payload, source="api")
        db.commit()
    except OrderError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except IntegrityError:
        db.rollback()  # the same external_id arrived twice at the same moment
        existing = db.scalar(select(Order).where(Order.store_id == store.id, Order.external_id == external_id[:80]))
        if existing:
            return JSONResponse(_order_json(existing), status_code=200)
        raise HTTPException(status_code=409, detail="conflict")
    return JSONResponse(_order_json(order), status_code=201)


@router.get("/api/v1/orders/{order_id}")
def api_get_order(order_id: str, x_api_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    store = _store_from_key(db, x_api_key)
    order = db.scalar(select(Order).where(Order.store_id == store.id,
                                          (Order.id == order_id) | (Order.external_id == order_id)))
    if not order:
        raise HTTPException(status_code=404, detail="not found")
    return _order_json(order)


# ---------------------------------------------------------------- WhatsApp Cloud API webhook

def _stores_by_phone_number_id(db: Session) -> dict[str, Store]:
    found = {}
    for store in db.scalars(select(Store)):
        cfg = get_settings(store)
        if cfg.get("whatsapp_mode") == "cloud" and cfg.get("wa_phone_number_id"):
            found[cfg["wa_phone_number_id"]] = store
    return found


@router.get("/webhooks/whatsapp")
def whatsapp_verify(db: Session = Depends(get_db), mode: str = Query("", alias="hub.mode"),
                    token: str = Query("", alias="hub.verify_token"), challenge: str = Query("", alias="hub.challenge")):
    if mode == "subscribe" and token:
        for store in db.scalars(select(Store)):
            expected = get_settings(store).get("wa_verify_token") or ""
            if expected and hmac.compare_digest(expected, token):
                return PlainTextResponse(challenge)
    raise HTTPException(status_code=403)


@router.post("/webhooks/whatsapp")
async def whatsapp_inbound(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400)
    stores = _stores_by_phone_number_id(db)
    handled = 0
    for message in whatsapp.parse_inbound(payload):
        store = stores.get(message["phone_number_id"])
        if not store:
            continue
        cfg = get_settings(store)
        if not whatsapp.verify_signature(cfg.get("wa_app_secret", ""), body,
                                         request.headers.get("x-hub-signature-256")):
            log.warning("bad signature for store %s", store.id)
            raise HTTPException(status_code=401)
        if message["id"] and db.scalar(select(Message.id).where(Message.store_id == store.id,
                                                                Message.provider_id == message["id"])):
            continue  # Meta retries webhooks; we already have this one
        phone, _ = normalize_phone(message["from"])
        order = db.scalar(select(Order).where(Order.store_id == store.id, Order.phone == phone)
                          .order_by(Order.stage.in_(("pending", "new", "no_answer", "postponed", "confirmed")).desc(),
                                    Order.created_at.desc()).limit(1))
        stop = campaigns.is_stop(message["text"])
        if not order or stop or order.stage not in ("pending", "new", "no_answer", "postponed", "confirmed"):
            # not an answer to a confirmation: it goes to the inbox (questions, new buyers, STOP)
            contact = notify.contact_for(db, store.id, "whatsapp", phone, message.get("name", ""))
            db.add(Message(store_id=store.id, order_id=order.id if order else None, contact_id=contact.id,
                           direction="in", text=message["text"][:4000], provider_id=message["id"] or None,
                           status="received"))
            notify.touch(contact, inbound=True)
            if stop:
                contact.opted_out = True
            elif order is None:  # a new buyer, not someone with an order in progress
                db.flush()
                notify.dm_auto_reply(db, store, contact, settings.public_url or str(request.base_url))
            db.commit()
            handled += 1
            continue
        reading = read_buyer_reply(db, store, order, message["text"], provider_id=message["id"] or None)
        applied = apply_reading(db, order, reading)
        if applied and cfg.get("auto_reply") and reading.answer:
            try:
                provider_id = whatsapp.cloud_send_text(store, order.phone, reading.answer)
                log_outbound(db, order, reading.answer, provider_id=provider_id or None, status="sent", ai=True)
            except whatsapp.CloudError as exc:
                log.info("auto reply failed: %s", exc)
        db.commit()
        handled += 1
    return {"ok": True, "handled": handled}


# ---------------------------------------------------------------- cron

@router.post("/tasks/run")
def tasks_run(x_cron_token: str | None = Header(default=None)):
    if not settings.cron_token or not x_cron_token or not hmac.compare_digest(settings.cron_token, x_cron_token):
        raise HTTPException(status_code=403)
    return run_followups()
