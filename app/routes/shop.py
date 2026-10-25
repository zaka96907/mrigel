"""Public order form (/f/<product id>), shop webhooks (Shopify, WooCommerce, YouCan) and the Meta
webhook for Messenger and Instagram."""

import hmac
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import campaigns, meta, notify, shops, storefront, whatsapp
from ..config import settings
from ..db import get_db
from ..models import Cart, Message, Order, Store
from ..ratelimit import limiter
from ..services import OrderError, create_order
from ..store_settings import get_settings
from ..web import render

router = APIRouter()
log = logging.getLogger("mrigel.shop")


# ================================================================ order form

def _form_context(db, product, store, token: str, values: dict | None = None, errors: dict | None = None) -> dict:
    upsell = storefront.upsell_for(db, product)
    values = values or {"qty": 1, "delivery_type": "home"}
    return {"product": product, "shop": store, "upsell": upsell, "token": token, "values": values,
            "errors": errors or {}, "money": storefront.totals(product, upsell, {**{"qty": 1, "upsell": False}, **values}),
            "out_of_stock": product.track_stock and product.stock <= 0}


def _load(db, product_id: str):
    found = storefront.form_product(db, product_id)
    if not found:
        raise HTTPException(status_code=404)
    return found


@router.get("/f/{product_id}")
def form_page(product_id: str, request: Request, db: Session = Depends(get_db)):
    product, store = _load(db, product_id)
    return render(request, "shop/form.html", _form_context(db, product, store, storefront.new_token(product.id)))


@router.post("/f/{product_id}/draft", dependencies=[Depends(limiter("form_draft", 60, 600))])
async def form_draft(product_id: str, request: Request, db: Session = Depends(get_db)):
    """Saves the cart while the buyer types (called by the page once the phone is filled)."""
    product, store = _load(db, product_id)
    form = await request.form()
    key = storefront.read_token(str(form.get("token", "")), product.id)
    if not key:
        return Response(status_code=400)
    try:
        storefront.save_cart(db, store, product, key, storefront.clean_form(dict(form)))
        db.commit()
    except IntegrityError:
        db.rollback()
    return Response(status_code=204)


@router.post("/f/{product_id}", dependencies=[Depends(limiter("form_submit", 20, 600))])
async def form_submit(product_id: str, request: Request, db: Session = Depends(get_db)):
    product, store = _load(db, product_id)
    form = await request.form()
    token = str(form.get("token", ""))
    key = storefront.read_token(token, product.id)
    data = storefront.clean_form(dict(form))
    if not key:
        return render(request, "shop/form.html", {**_form_context(db, product, store, storefront.new_token(product.id),
                                                                  data, {"form": "form_err_expired"})}, status_code=400)
    errors = storefront.validate(data)
    if errors:
        return render(request, "shop/form.html", _form_context(db, product, store, token, data, errors), status_code=400)
    cart = storefront.save_cart(db, store, product, key, data)
    if cart is None or cart.status in ("ordered", "recovered"):
        db.rollback()
        return render(request, "shop/thanks.html", {"shop": store, "product": product, "order": None,
                                                    "thanks": get_settings(store).get("form_thanks")})
    if storefront.otp_enabled(store):
        result = storefront.send_otp(db, store, cart)
        db.commit()
        if result == "sent":
            return render(request, "shop/otp.html", {"shop": store, "product": product, "token": token, "error": ""})
        log.info("OTP not sent for cart %s (%s); creating the order without it", cart.id, result)
    order = storefront.place_order(db, store, product, cart, data)
    db.commit()
    return render(request, "shop/thanks.html", {"shop": store, "product": product, "order": order,
                                                "thanks": get_settings(store).get("form_thanks")})


@router.post("/f/{product_id}/otp", dependencies=[Depends(limiter("form_otp", 30, 600))])
async def form_otp(product_id: str, request: Request, db: Session = Depends(get_db)):
    product, store = _load(db, product_id)
    form = await request.form()
    token = str(form.get("token", ""))
    key = storefront.read_token(token, product.id)
    cart = db.scalar(select(Cart).where(Cart.token == key)) if key else None
    if cart is None or cart.store_id != store.id:
        raise HTTPException(status_code=400)
    if cart.status in ("ordered", "recovered"):
        return render(request, "shop/thanks.html", {"shop": store, "product": product, "order": None,
                                                    "thanks": get_settings(store).get("form_thanks")})
    if form.get("resend"):
        result = storefront.send_otp(db, store, cart)
        db.commit()
        return render(request, "shop/otp.html", {"shop": store, "product": product, "token": token,
                                                 "error": "" if result == "sent" else "form_otp_limit"})
    result = storefront.check_otp(cart, str(form.get("code", "")))
    if result != "ok":
        db.commit()
        return render(request, "shop/otp.html", {"shop": store, "product": product, "token": token,
                                                 "error": f"form_otp_{result}"}, status_code=400)
    data = storefront.clean_form({"customer_name": cart.customer_name, "phone": cart.phone, **(cart.data or {})})
    order = storefront.place_order(db, store, product, cart, data)
    db.commit()
    return render(request, "shop/thanks.html", {"shop": store, "product": product, "order": order,
                                                "thanks": get_settings(store).get("form_thanks")})


# ================================================================ Shopify / WooCommerce / YouCan

@router.post("/webhooks/shop/{shop}/{store_id}", dependencies=[Depends(limiter("shop_hook", 300, 60))])
async def shop_webhook(shop: str, store_id: str, request: Request, db: Session = Depends(get_db)):
    if shop not in shops.MAPPERS:
        raise HTTPException(status_code=404)
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=404)
    body = await request.body()
    secret = get_settings(store).get(shops.SECRET_SETTING[shop], "")
    signature = request.headers.get(shops.SIGNATURE_HEADERS[shop])
    if shop == "woocommerce" and not signature and body.startswith(b"webhook_id="):
        return {"ok": True, "ping": True}  # WooCommerce pings a new webhook with a form body, unsigned
    if not shops.verify(shop, secret, body, signature):
        raise HTTPException(status_code=401, detail="bad signature")
    topic = request.headers.get(shops.TOPIC_HEADERS[shop], "")
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="body must be JSON")
    if shop == "youcan":
        topic = topic or str(payload.get("event_name", ""))
    if topic and topic not in shops.ORDER_TOPICS[shop]:
        return {"ok": True, "ignored": topic}
    data = shops.MAPPERS[shop](payload)
    existing = db.scalar(select(Order).where(Order.store_id == store.id, Order.external_id == data["external_id"][:80]))
    if existing:
        return {"ok": True, "id": existing.id, "duplicate": True}  # shops retry; one order per shop order
    try:
        order = create_order(db, store, data, source=shop)
        db.commit()
    except OrderError as exc:
        db.rollback()
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)
    except IntegrityError:
        db.rollback()
        return {"ok": True, "duplicate": True}
    return JSONResponse({"ok": True, "id": order.id}, status_code=201)


# ================================================================ Messenger and Instagram

def _store_for_account(db, account_id: str) -> Store | None:
    for store in db.scalars(select(Store)):
        cfg = get_settings(store)
        if account_id and account_id in (cfg.get("fb_page_id"), cfg.get("ig_account_id")):
            return store
    return None


@router.get("/webhooks/meta")
def meta_verify(db: Session = Depends(get_db), mode: str = Query("", alias="hub.mode"),
                token: str = Query("", alias="hub.verify_token"), challenge: str = Query("", alias="hub.challenge")):
    if mode == "subscribe" and token:
        for store in db.scalars(select(Store)):
            expected = get_settings(store).get("wa_verify_token") or ""
            if expected and hmac.compare_digest(expected, token):
                return PlainTextResponse(challenge)
    raise HTTPException(status_code=403)


@router.post("/webhooks/meta")
async def meta_inbound(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400)
    handled = 0
    for item in meta.parse_inbound(payload):
        store = _store_for_account(db, item["account_id"])
        if store is None:
            continue
        if not whatsapp.verify_signature(get_settings(store).get("wa_app_secret", ""), body,
                                         request.headers.get("x-hub-signature-256")):
            raise HTTPException(status_code=401)
        if item["id"] and db.scalar(select(Message.id).where(Message.store_id == store.id,
                                                             Message.provider_id == item["id"])):
            continue
        contact = notify.contact_for(db, store.id, item["channel"], item["sender"])
        db.add(Message(store_id=store.id, contact_id=contact.id, direction="in", text=item["text"],
                       channel=item["channel"], provider_id=item["id"] or None, status="received"))
        notify.touch(contact, inbound=True)
        if campaigns.is_stop(item["text"]):
            contact.opted_out = True
        else:
            db.flush()
            notify.dm_auto_reply(db, store, contact, settings.public_url or str(request.base_url))
        db.commit()
        handled += 1
    return {"ok": True, "handled": handled}
