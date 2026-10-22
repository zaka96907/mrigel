"""Signed-in pages added after the core loop: products and stock, money (COD reconciliation and the
monthly statement), automations, the inbox, campaigns, abandoned carts, saved views, integrations."""

import re
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import campaigns as campaign_lib
from .. import catalog, finance, meta, notify, rules, storefront, whatsapp
from ..carriers import CARRIERS
from ..db import get_db
from ..models import (STAGES, Campaign, Cart, Contact, Message, Order, Payout, Product, Rule, SavedView,
                      StockMove, Store, User, utcnow)
from ..pdf import monthly_statement
from ..services import add_event, as_utc, queue_size
from ..store_settings import SECRET_KEYS, get_settings
from ..web import check_csrf, current_store, current_user, flash, get_lang, owner_only, render, scoped_order

router = APIRouter()
MAX_UPLOAD = 4 * 1024 * 1024


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _shell(db: Session, store: Store, user: User, nav: str) -> dict:
    unread = db.scalar(select(func.coalesce(func.sum(Contact.unread), 0)).where(Contact.store_id == store.id)) or 0
    return {"store": store, "user": user, "queue_count": queue_size(db, store.id), "nav": nav, "inbox_unread": unread}


def _int(value, default: int = 0, low: int = 0, high: int = 10_000_000) -> int:
    try:
        return max(low, min(high, int(float(str(value).replace(" ", "") or default))))
    except (TypeError, ValueError):
        return default


def _is_demo(store: Store) -> bool:
    return bool((store.settings or {}).get("demo"))


def _cloud(store: Store) -> bool:
    return get_settings(store).get("whatsapp_mode") == "cloud" and not _is_demo(store)


def _scoped(db: Session, model, store: Store, row_id: str):
    row = db.scalar(select(model).where(model.id == row_id, model.store_id == store.id))
    if row is None:
        raise HTTPException(status_code=404)
    return row


# ================================================================ products and stock

@router.get("/products")
def products(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
             store: Store = Depends(current_store)):
    rows = db.scalars(select(Product).where(Product.store_id == store.id)
                      .order_by(Product.active.desc(), Product.name)).all()
    return render(request, "products/list.html", {**_shell(db, store, user, "products"), "products": rows,
                                                  "stock_value": catalog.stock_value(db, store.id),
                                                  "base": str(request.base_url).rstrip("/")})


def _product_values(form) -> dict:
    return {
        "sku": re.sub(r"\s+", "-", str(form.get("sku", "")).strip())[:60],
        "name": str(form.get("name", "")).strip()[:120],
        "description": str(form.get("description", "")).strip()[:2000],
        "price_dzd": _int(form.get("price_dzd")),
        "cost_dzd": _int(form.get("cost_dzd")),
        "delivery_fee_dzd": _int(form.get("delivery_fee_dzd")),
        "low_stock": _int(form.get("low_stock"), 5),
        "track_stock": form.get("track_stock") == "on",
        "form_enabled": form.get("form_enabled") == "on",
        "active": form.get("active") == "on",
        "upsell_product_id": str(form.get("upsell_product_id", "")) or None,
        "upsell_price_dzd": _int(form.get("upsell_price_dzd")),
    }


def _product_page(request, db, store, user, product: Product | None, values: dict, error: str = "", status: int = 200):
    others = db.scalars(select(Product).where(Product.store_id == store.id, Product.active.is_(True))
                        .order_by(Product.name)).all()
    moves = []
    if product is not None:
        moves = db.scalars(select(StockMove).where(StockMove.product_id == product.id)
                           .order_by(StockMove.created_at.desc()).limit(30)).all()
    base = str(request.base_url).rstrip("/")
    return render(request, "products/edit.html", {**_shell(db, store, user, "products"), "product": product,
                                                  "values": values, "error": error, "others": others, "moves": moves,
                                                  "form_url": f"{base}/f/{product.id}" if product else ""},
                  status_code=status)


@router.get("/products/new")
def product_new_page(request: Request, db: Session = Depends(get_db), user: User = Depends(owner_only),
                     store: Store = Depends(current_store)):
    return _product_page(request, db, store, user, None, {"track_stock": True, "form_enabled": True, "active": True,
                                                          "low_stock": 5})


@router.post("/products/new", dependencies=[Depends(check_csrf)])
async def product_create(request: Request, db: Session = Depends(get_db), user: User = Depends(owner_only),
                         store: Store = Depends(current_store)):
    form = await request.form()
    values = _product_values(form)
    values["active"] = True
    stock = _int(form.get("stock"))
    error = _product_error(db, store, values)
    if error:
        return _product_page(request, db, store, user, None, {**values, "stock": stock}, error, 400)
    product = Product(store_id=store.id, **values)
    db.add(product)
    db.flush()
    if stock:
        catalog.adjust(db, product, stock, "initial")
    db.commit()
    flash(request, "saved_ok")
    return _redirect(f"/products/{product.id}")


def _product_error(db, store, values: dict, product_id: str | None = None) -> str:
    if not values["name"] or not values["sku"]:
        return "err_product_fields"
    clash = db.scalar(select(Product.id).where(Product.store_id == store.id, Product.sku == values["sku"]))
    if clash and clash != product_id:
        return "err_sku_taken"
    if values["upsell_product_id"]:
        upsell = db.scalar(select(Product.id).where(Product.store_id == store.id,
                                                    Product.id == values["upsell_product_id"]))
        if not upsell or upsell == product_id:
            values["upsell_product_id"] = None
    return ""


@router.get("/products/{product_id}")
def product_page(product_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
                 store: Store = Depends(current_store)):
    product = _scoped(db, Product, store, product_id)
    values = {c: getattr(product, c) for c in ("sku", "name", "description", "price_dzd", "cost_dzd", "delivery_fee_dzd",
                                               "low_stock", "track_stock", "form_enabled", "active",
                                               "upsell_product_id", "upsell_price_dzd", "stock")}
    return _product_page(request, db, store, user, product, values)


@router.post("/products/{product_id}", dependencies=[Depends(check_csrf)])
async def product_save(product_id: str, request: Request, db: Session = Depends(get_db),
                       user: User = Depends(owner_only), store: Store = Depends(current_store)):
    product = _scoped(db, Product, store, product_id)
    form = await request.form()
    values = _product_values(form)
    error = _product_error(db, store, values, product.id)
    if error:
        return _product_page(request, db, store, user, product, {**values, "stock": product.stock}, error, 400)
    for key, value in values.items():
        setattr(product, key, value)
    db.commit()
    flash(request, "saved_ok")
    return _redirect(f"/products/{product.id}")


@router.post("/products/{product_id}/stock", dependencies=[Depends(check_csrf)])
def product_stock(product_id: str, request: Request, delta: str = Form("0"), db: Session = Depends(get_db),
                  user: User = Depends(owner_only), store: Store = Depends(current_store)):
    product = _scoped(db, Product, store, product_id)
    change = _int(delta, 0, -100_000, 100_000)
    if change:
        catalog.adjust(db, product, change, "manual")
        db.commit()
        flash(request, "saved_ok")
    return _redirect(f"/products/{product.id}#stock")


# ================================================================ money

@router.get("/finance")
def finance_page(request: Request, db: Session = Depends(get_db), user: User = Depends(owner_only),
                 store: Store = Depends(current_store)):
    payouts = db.scalars(select(Payout).where(Payout.store_id == store.id).order_by(Payout.created_at.desc())
                         .limit(20)).all()
    now = utcnow()
    months = []
    year, month = now.year, now.month
    for _ in range(6):
        months.append(f"{year}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return render(request, "finance.html", {**_shell(db, store, user, "finance"), "f": finance.summary(db, store),
                                            "payouts": payouts, "carriers": CARRIERS, "months": months})


@router.post("/finance/payout", dependencies=[Depends(check_csrf)])
async def finance_upload(request: Request, file: UploadFile = File(...), carrier: str = Form(""),
                         db: Session = Depends(get_db), user: User = Depends(owner_only),
                         store: Store = Depends(current_store)):
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD or not data:
        flash(request, "err_file_big" if data else "err_empty_file", "error")
        return _redirect("/finance")
    payout = finance.reconcile(db, store, data, file.filename or "", carrier if carrier in CARRIERS else "", user.id)
    if not payout.rows:
        db.rollback()
        flash(request, "err_payout_columns", "error")
        return _redirect("/finance")
    db.commit()
    return _redirect(f"/finance/payouts/{payout.id}")


@router.get("/finance/payouts/{payout_id}")
def payout_page(payout_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(owner_only),
                store: Store = Depends(current_store)):
    payout = _scoped(db, Payout, store, payout_id)
    orders = db.scalars(select(Order).where(Order.store_id == store.id, Order.payout_id == payout.id)
                        .order_by(Order.paid_at)).all()
    return render(request, "payout.html", {**_shell(db, store, user, "finance"), "payout": payout, "orders": orders,
                                           "carriers": CARRIERS})


@router.get("/finance/statement")
def statement(month: str = "", db: Session = Depends(get_db), user: User = Depends(owner_only),
              store: Store = Depends(current_store)):
    if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", month):
        raise HTTPException(status_code=404)
    pdf = monthly_statement(store.name, finance.month_figures(db, store, month))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="mrigel-releve-{month}.pdf"'})


# ================================================================ automations

@router.get("/automations")
def automations(request: Request, db: Session = Depends(get_db), user: User = Depends(owner_only),
                store: Store = Depends(current_store)):
    rows = db.scalars(select(Rule).where(Rule.store_id == store.id).order_by(Rule.created_at)).all()
    members = db.scalars(select(User).where(User.store_id == store.id, User.active.is_(True))).all()
    return render(request, "automations.html", {**_shell(db, store, user, "automations"), "rules": rows,
                                                "fields": rules.FIELDS, "ops": rules.OPS, "actions": rules.ACTIONS,
                                                "templates": rules.TEMPLATES, "members": members,
                                                "names": {m.id: m.name for m in members}})


@router.post("/automations", dependencies=[Depends(check_csrf)])
async def automation_create(request: Request, db: Session = Depends(get_db), user: User = Depends(owner_only),
                            store: Store = Depends(current_store)):
    form = await request.form()
    event, conditions, actions = rules.clean_rule({k: v for k, v in form.items()})
    name = str(form.get("name", "")).strip()[:120]
    if not name or not event or not actions:
        flash(request, "err_rule_fields", "error")
        return _redirect("/automations")
    db.add(Rule(store_id=store.id, name=name, event=event, conditions=conditions, actions=actions))
    db.commit()
    flash(request, "saved_ok")
    return _redirect("/automations")


@router.post("/automations/template/{key}", dependencies=[Depends(check_csrf)])
def automation_template(key: str, request: Request, db: Session = Depends(get_db), user: User = Depends(owner_only),
                        store: Store = Depends(current_store)):
    template = next((t for t in rules.TEMPLATES if t["key"] == key), None)
    if template is None:
        raise HTTPException(status_code=404)
    from ..i18n import translate

    db.add(Rule(store_id=store.id, name=translate(f"rule_tpl_{key}", get_lang(request)), event=template["event"],
                conditions=template["conditions"], actions=template["actions"]))
    db.commit()
    flash(request, "saved_ok")
    return _redirect("/automations")


@router.post("/automations/{rule_id}/toggle", dependencies=[Depends(check_csrf)])
def automation_toggle(rule_id: str, db: Session = Depends(get_db), user: User = Depends(owner_only),
                      store: Store = Depends(current_store)):
    rule = _scoped(db, Rule, store, rule_id)
    rule.active = not rule.active
    db.commit()
    return _redirect("/automations")


@router.post("/automations/{rule_id}/delete", dependencies=[Depends(check_csrf)])
def automation_delete(rule_id: str, db: Session = Depends(get_db), user: User = Depends(owner_only),
                      store: Store = Depends(current_store)):
    db.delete(_scoped(db, Rule, store, rule_id))
    db.commit()
    return _redirect("/automations")


# ================================================================ inbox

@router.get("/inbox")
def inbox(request: Request, c: str = "", channel: str = "", db: Session = Depends(get_db),
          user: User = Depends(current_user), store: Store = Depends(current_store)):
    query = select(Contact).where(Contact.store_id == store.id, Contact.last_message_at.is_not(None))
    if channel in ("whatsapp", "messenger", "instagram"):
        query = query.where(Contact.channel == channel)
    contacts = db.scalars(query.order_by(Contact.last_message_at.desc()).limit(200)).all()
    current = _scoped(db, Contact, store, c) if c else None
    thread, orders = [], []
    if current is not None:
        if current.unread:
            current.unread = 0
            db.commit()
        thread = db.scalars(select(Message).where(Message.contact_id == current.id)
                            .order_by(Message.created_at.desc()).limit(100)).all()[::-1]
        if current.channel == "whatsapp":
            orders = db.scalars(select(Order).where(Order.store_id == store.id, Order.phone == current.handle)
                                .order_by(Order.created_at.desc()).limit(10)).all()
    return render(request, "inbox.html", {**_shell(db, store, user, "inbox"), "contacts": contacts,
                                          "current": current, "thread": thread, "orders": orders,
                                          "channel": channel, "cloud": _cloud(store),
                                          "meta_ready": bool(get_settings(store).get("fb_page_token"))})


@router.post("/inbox/{contact_id}/reply", dependencies=[Depends(check_csrf)])
def inbox_reply(contact_id: str, request: Request, text: str = Form(""), db: Session = Depends(get_db),
                user: User = Depends(current_user), store: Store = Depends(current_store)):
    contact = _scoped(db, Contact, store, contact_id)
    text = text.strip()[:2000]
    back = f"/inbox?c={contact.id}"
    if not text:
        return _redirect(back)
    message = Message(store_id=store.id, contact_id=contact.id, direction="out", text=text, kind="chat")
    if contact.channel == "whatsapp" and not _cloud(store):
        message.status = "opened"
        db.add(message)
        notify.touch(contact, inbound=False)
        db.commit()
        if _is_demo(store):
            flash(request, "demo_not_sent")
            return _redirect(back)
        return _redirect(whatsapp.wa_link(contact.handle, text))
    if _is_demo(store):
        flash(request, "demo_not_sent")
        return _redirect(back)
    try:
        if contact.channel == "whatsapp":
            message.provider_id = whatsapp.cloud_send_text(store, contact.handle, text) or None
        else:
            message.provider_id = meta.send_text(store, contact.channel, contact.handle, text) or None
        message.status = "sent"
    except whatsapp.CloudError as exc:
        flash(request, "err_cloud_send", "error", e=str(exc))
        return _redirect(back)
    db.add(message)
    notify.touch(contact, inbound=False)
    db.commit()
    return _redirect(back)


@router.post("/inbox/{contact_id}/optout", dependencies=[Depends(check_csrf)])
def inbox_optout(contact_id: str, db: Session = Depends(get_db), user: User = Depends(current_user),
                 store: Store = Depends(current_store)):
    contact = _scoped(db, Contact, store, contact_id)
    contact.opted_out = not contact.opted_out
    db.commit()
    return _redirect(f"/inbox?c={contact.id}")


# ================================================================ messages waiting on an order (assisted mode)

@router.post("/orders/{order_id}/out", dependencies=[Depends(check_csrf)])
def order_out_for_delivery(order_id: str, request: Request, db: Session = Depends(get_db),
                           user: User = Depends(current_user), store: Store = Depends(current_store)):
    order = scoped_order(db, store, order_id)
    if order.stage != "shipped":
        flash(request, "err_bad_transition", "error")
        return _redirect(f"/orders/{order.id}")
    message = notify.out_for_delivery(db, order, user.id)
    add_event(db, order, "system", "out_for_delivery", user_id=user.id)
    db.commit()
    flash(request, "notice_queued" if message else "err_phone_required", "success" if message else "error")
    return _redirect(f"/orders/{order.id}#messages")


@router.post("/messages/{message_id}/open", dependencies=[Depends(check_csrf)])
def message_open(message_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
                 store: Store = Depends(current_store)):
    """Assisted mode: the agent sends a waiting message from their own WhatsApp with one tap."""
    message = _scoped(db, Message, store, message_id)
    contact = db.get(Contact, message.contact_id) if message.contact_id else None
    if message.direction != "out" or message.status != "todo" or contact is None or contact.channel != "whatsapp":
        raise HTTPException(status_code=404)
    message.status = "opened"
    db.commit()
    back = f"/orders/{message.order_id}#messages" if message.order_id else f"/inbox?c={contact.id}"
    if _is_demo(store):
        flash(request, "demo_not_sent")
        return _redirect(back)
    return _redirect(whatsapp.wa_link(contact.handle, message.text))


# ================================================================ campaigns

def _audience_from(form) -> tuple[list[str], list[int], int]:
    stages = [s for s in form.getlist("stages") if s in STAGES] or ["delivered"]
    wilayas = sorted({int(w) for w in form.getlist("wilayas") if str(w).isdigit() and 1 <= int(w) <= 69})
    return stages, wilayas, _int(form.get("days"), 0, 0, 3650)


@router.get("/campaigns")
def campaigns(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
              store: Store = Depends(current_store)):
    rows = db.scalars(select(Campaign).where(Campaign.store_id == store.id).order_by(Campaign.created_at.desc())).all()
    return render(request, "campaigns/list.html", {**_shell(db, store, user, "campaigns"), "campaigns": rows,
                                                   "cloud": _cloud(store),
                                                   "template_set": bool(get_settings(store).get("wa_campaign_template"))})


@router.post("/campaigns", dependencies=[Depends(check_csrf)])
async def campaign_create(request: Request, db: Session = Depends(get_db), user: User = Depends(owner_only),
                          store: Store = Depends(current_store)):
    form = await request.form()
    name, text = str(form.get("name", "")).strip()[:120], str(form.get("text", "")).strip()[:1000]
    if not name or not text:
        flash(request, "err_fields", "error")
        return _redirect("/campaigns")
    stages, wilayas, days = _audience_from(form)
    recipients = campaign_lib.audience(db, store, stages, wilayas, days)
    campaign = Campaign(store_id=store.id, name=name, text=text, created_by_id=user.id, recipients=recipients,
                        audience={"stages": stages, "wilayas": wilayas, "days": days})
    db.add(campaign)
    db.commit()
    return _redirect(f"/campaigns/{campaign.id}")


@router.get("/campaigns/{campaign_id}")
def campaign_page(campaign_id: str, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(current_user), store: Store = Depends(current_store)):
    campaign = _scoped(db, Campaign, store, campaign_id)
    sample = campaign_lib.personal_text(campaign, store, (campaign.recipients or [{"name": "Amina"}])[0])
    return render(request, "campaigns/detail.html", {**_shell(db, store, user, "campaigns"), "c": campaign,
                                                     "sample": sample, "cloud": _cloud(store),
                                                     "template_set": bool(get_settings(store).get("wa_campaign_template"))})


@router.post("/campaigns/{campaign_id}/send", dependencies=[Depends(check_csrf)])
def campaign_send(campaign_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(owner_only),
                  store: Store = Depends(current_store)):
    campaign = _scoped(db, Campaign, store, campaign_id)
    if not _cloud(store):
        flash(request, "err_cloud_not_configured", "error")
        return _redirect(f"/campaigns/{campaign.id}")
    queued = campaign_lib.send_cloud(db, store, campaign)
    db.commit()
    flash(request, "campaign_queued", n=queued)
    return _redirect(f"/campaigns/{campaign.id}")


@router.post("/campaigns/{campaign_id}/open", dependencies=[Depends(check_csrf)])
def campaign_open(campaign_id: str, request: Request, phone: str = Form(""), db: Session = Depends(get_db),
                  user: User = Depends(current_user), store: Store = Depends(current_store)):
    campaign = _scoped(db, Campaign, store, campaign_id)
    recipient = next((r for r in campaign.recipients or [] if r.get("phone") == phone), None)
    if recipient is None:
        raise HTTPException(status_code=404)
    text = campaign_lib.personal_text(campaign, store, recipient)
    campaign_lib.mark(campaign, phone, "sent")
    contact = notify.contact_for(db, store.id, "whatsapp", phone, recipient.get("name", ""))
    db.add(Message(store_id=store.id, contact_id=contact.id, direction="out", text=text, kind="campaign",
                   status="opened"))
    notify.touch(contact, inbound=False)
    db.commit()
    if _is_demo(store):
        flash(request, "demo_not_sent")
        return _redirect(f"/campaigns/{campaign.id}")
    return _redirect(whatsapp.wa_link(phone, text))


@router.post("/campaigns/{campaign_id}/skip", dependencies=[Depends(check_csrf)])
def campaign_skip(campaign_id: str, phone: str = Form(""), db: Session = Depends(get_db),
                  user: User = Depends(current_user), store: Store = Depends(current_store)):
    campaign = _scoped(db, Campaign, store, campaign_id)
    campaign_lib.mark(campaign, phone, "skipped")
    db.commit()
    return _redirect(f"/campaigns/{campaign.id}")


# ================================================================ abandoned carts

@router.get("/carts")
def carts(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
          store: Store = Depends(current_store)):
    rows = storefront.abandoned(db, store)
    names = {p.id: p.name for p in db.scalars(select(Product).where(Product.store_id == store.id))}
    since = utcnow() - timedelta(days=30)
    recovered = db.scalar(select(func.count()).select_from(Cart).where(
        Cart.store_id == store.id, Cart.status == "recovered", Cart.updated_at >= since)) or 0
    ordered = db.scalar(select(func.count()).select_from(Cart).where(
        Cart.store_id == store.id, Cart.status == "ordered", Cart.updated_at >= since)) or 0
    return render(request, "carts.html", {**_shell(db, store, user, "carts"), "carts": rows, "names": names,
                                          "recovered": recovered, "ordered": ordered, "cloud": _cloud(store)})


@router.post("/carts/{cart_id}/recover", dependencies=[Depends(check_csrf)])
def cart_recover(cart_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
                 store: Store = Depends(current_store)):
    cart = _scoped(db, Cart, store, cart_id)
    text = storefront.recovery_text(db, store, cart)
    cart.recovery_sent_at = utcnow()
    if _cloud(store):
        notify.queue_to_phone(db, store, cart.phone, cart.customer_name, text, "recovery")
        db.commit()
        flash(request, "notice_queued")
        return _redirect("/carts")
    contact = notify.contact_for(db, store.id, "whatsapp", cart.phone, cart.customer_name)
    db.add(Message(store_id=store.id, contact_id=contact.id, direction="out", text=text, kind="recovery",
                   status="opened"))
    notify.touch(contact, inbound=False)
    db.commit()
    if _is_demo(store):
        flash(request, "demo_not_sent")
        return _redirect("/carts")
    return _redirect(whatsapp.wa_link(cart.phone, text))


@router.post("/carts/{cart_id}/order", dependencies=[Depends(check_csrf)])
def cart_to_order(cart_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
                  store: Store = Depends(current_store)):
    """The buyer said yes on WhatsApp: turn the cart into an order without retyping it."""
    cart = _scoped(db, Cart, store, cart_id)
    product = db.get(Product, cart.product_id) if cart.product_id else None
    if product is None or cart.status not in ("open", "otp"):
        raise HTTPException(status_code=404)
    data = {"customer_name": cart.customer_name or "—", "phone": cart.phone, **(cart.data or {})}
    data = storefront.clean_form(data)
    order = storefront.place_order(db, store, product, cart, data)
    cart.status = "recovered"
    db.commit()
    return _redirect(f"/orders/{order.id}")


@router.post("/carts/{cart_id}/dismiss", dependencies=[Depends(check_csrf)])
def cart_dismiss(cart_id: str, db: Session = Depends(get_db), user: User = Depends(current_user),
                 store: Store = Depends(current_store)):
    cart = _scoped(db, Cart, store, cart_id)
    cart.status = "dismissed"
    db.commit()
    return _redirect("/carts")


# ================================================================ saved views and dashboard layout

ORDER_FILTERS = ("stage", "q", "wilaya", "tag", "source", "risk")


@router.post("/views", dependencies=[Depends(check_csrf)])
def view_save(request: Request, name: str = Form(""), query: str = Form(""), db: Session = Depends(get_db),
              user: User = Depends(current_user), store: Store = Depends(current_store)):
    clean = urlencode([(k, v) for k, v in parse_qsl(query.lstrip("?")) if k in ORDER_FILTERS and v][:6])
    if name.strip() and clean:
        db.add(SavedView(store_id=store.id, user_id=user.id, name=name.strip()[:60], query=clean[:300]))
        db.commit()
        flash(request, "saved_ok")
    return _redirect("/orders?" + clean)


@router.post("/views/{view_id}/delete", dependencies=[Depends(check_csrf)])
def view_delete(view_id: str, db: Session = Depends(get_db), user: User = Depends(current_user),
                store: Store = Depends(current_store)):
    view = db.scalar(select(SavedView).where(SavedView.id == view_id, SavedView.user_id == user.id))
    if view is None:
        raise HTTPException(status_code=404)
    db.delete(view)
    db.commit()
    return _redirect("/orders")


DASHBOARD_PANELS = ("chart", "funnel", "wilayas", "agents", "products", "money")


@router.post("/dashboard/layout", dependencies=[Depends(check_csrf)])
async def dashboard_layout(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()
    shown = [p for p in DASHBOARD_PANELS if form.get(f"show_{p}") == "on"]
    prefs = dict(user.prefs or {})
    prefs["hidden_panels"] = [p for p in DASHBOARD_PANELS if p not in shown]
    days = _int(form.get("days"), 30)
    prefs["days"] = days if days in (7, 30, 90) else 30
    user.prefs = prefs
    db.commit()
    flash(request, "saved_ok")
    return _redirect("/dashboard")


# ================================================================ integrations (owner)

@router.get("/integrations")
def integrations(request: Request, db: Session = Depends(get_db), user: User = Depends(owner_only),
                 store: Store = Depends(current_store)):
    cfg = get_settings(store)
    base = str(request.base_url).rstrip("/")
    products = db.scalars(select(Product).where(Product.store_id == store.id, Product.active.is_(True),
                                                Product.form_enabled.is_(True)).order_by(Product.name)).all()
    return render(request, "integrations.html", {
        **_shell(db, store, user, "integrations"), "cfg": cfg,
        "secrets_set": {k: bool(cfg.get(k)) for k in SECRET_KEYS},
        "hooks": {shop: f"{base}/webhooks/shop/{shop}/{store.id}" for shop in ("shopify", "woocommerce", "youcan")},
        "meta_hook": f"{base}/webhooks/meta", "base": base, "products": products,
    })
