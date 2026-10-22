"""The order form a merchant puts on their product page, Facebook or Instagram bio (/f/<product id>).

- One page, one product, COD: name, phone, wilaya, commune, address, home or stop desk, quantity,
  and an optional upsell checkbox.
- Works inside an iframe on any site, so it cannot rely on the session cookie: each form carries a
  signed token (itsdangerous) that names the cart.
- As soon as the buyer has typed a valid phone, the cart is saved (fetch, no reload). A cart that
  never becomes an order is an abandoned cart the team can recover on WhatsApp.
- Optional WhatsApp code (OTP) before the order is created, through the merchant's Cloud API and an
  approved authentication template. Codes are stored hashed, expire after 10 minutes, 5 tries.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select

from . import notify, whatsapp
from .algeria import normalize_phone, parse_wilaya
from .config import settings
from .models import Cart, Order, Product, Store, utcnow
from .services import as_utc, create_order
from .store_settings import get_settings

_signer = URLSafeTimedSerializer(settings.secret_key, salt="mrigel-form")
OTP_TTL = timedelta(minutes=10)
OTP_MAX_TRIES = 5
OTP_MAX_SENDS = 3


def new_token(product_id: str) -> str:
    return _signer.dumps({"p": product_id, "c": secrets.token_urlsafe(18)})


def read_token(token: str, product_id: str) -> str | None:
    """The cart key inside a valid token for this product, else None. Tokens live 24 h."""
    try:
        data = _signer.loads(token or "", max_age=24 * 3600)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict) or data.get("p") != product_id:
        return None
    return str(data.get("c") or "") or None


def form_product(db, product_id: str) -> tuple[Product, Store] | None:
    product = db.get(Product, product_id)
    if not product or not product.active or not product.form_enabled:
        return None
    store = db.get(Store, product.store_id)
    return (product, store) if store else None


def upsell_for(db, product: Product) -> Product | None:
    if not product.upsell_product_id:
        return None
    upsell = db.get(Product, product.upsell_product_id)
    if upsell and upsell.active and upsell.store_id == product.store_id and upsell.id != product.id:
        return upsell
    return None


def clean_form(form: dict) -> dict:
    qty = form.get("qty", "1")
    try:
        qty = max(1, min(10, int(qty)))
    except (TypeError, ValueError):
        qty = 1
    return {
        "customer_name": str(form.get("customer_name", "")).strip()[:120],
        "phone": str(form.get("phone", "")).strip()[:20],
        "wilaya": str(form.get("wilaya", "")).strip()[:40],
        "commune": str(form.get("commune", "")).strip()[:120],
        "address": str(form.get("address", "")).strip()[:255],
        "delivery_type": "stopdesk" if form.get("delivery_type") == "stopdesk" else "home",
        "qty": qty,
        "upsell": form.get("upsell") in ("1", "on", "true"),
    }


def validate(data: dict) -> dict:
    errors = {}
    if len(data["customer_name"]) < 2:
        errors["customer_name"] = "err_name_required"
    _, valid = normalize_phone(data["phone"])
    if not valid:
        errors["phone"] = "form_err_phone"
    if not parse_wilaya(data["wilaya"]):
        errors["wilaya"] = "form_err_wilaya"
    if data["delivery_type"] == "home" and not data["commune"]:
        errors["commune"] = "form_err_commune"
    return errors


def totals(product: Product, upsell: Product | None, data: dict) -> dict:
    items_total = product.price_dzd * data["qty"]
    upsell_price = 0
    if upsell and data.get("upsell"):
        upsell_price = product.upsell_price_dzd or upsell.price_dzd
    fee = product.delivery_fee_dzd or 0
    return {"items": items_total, "upsell": upsell_price, "fee": fee, "total": items_total + upsell_price + fee}


def save_cart(db, store: Store, product: Product, key: str, data: dict) -> Cart | None:
    """Create or update the cart for this token once the phone looks like a real mobile number."""
    phone, valid = normalize_phone(data.get("phone", ""))
    cart = db.scalar(select(Cart).where(Cart.token == key))
    if cart is None:
        if not valid:
            return None
        cart = Cart(store_id=store.id, product_id=product.id, token=key, otp_tries=0, otp_sends=0)
        db.add(cart)
        db.flush()  # the id is part of the code hash
    if cart.store_id != store.id or cart.status in ("ordered", "recovered"):
        return cart
    if valid:
        cart.phone = phone
    cart.customer_name = data.get("customer_name", "")[:120] or cart.customer_name
    cart.data = {**{k: v for k, v in data.items() if k not in ("customer_name", "phone")},
                 "wilaya_code": parse_wilaya(data.get("wilaya", ""))}
    cart.updated_at = utcnow()
    return cart


def place_order(db, store: Store, product: Product, cart: Cart, data: dict) -> Order:
    upsell = upsell_for(db, product)
    money = totals(product, upsell, data)
    items = [{"name": product.name, "qty": data["qty"], "price_dzd": product.price_dzd, "product_id": product.id}]
    if money["upsell"] and upsell:
        items.append({"name": upsell.name, "qty": 1, "price_dzd": money["upsell"], "product_id": upsell.id})
    order = create_order(db, store, {**data, "items": items, "total": money["total"], "delivery_fee": money["fee"],
                                     "tags": ["upsell"] if money["upsell"] else []}, source="form")
    cart.status = "ordered"
    cart.order_id = order.id
    return order


# ---------------------------------------------------------------- one-time code

def _hash(cart: Cart, code: str) -> str:
    return hmac.new(settings.secret_key.encode(), f"{cart.id}:{code}".encode(), hashlib.sha256).hexdigest()


def otp_enabled(store: Store) -> bool:
    cfg = get_settings(store)
    return bool(cfg.get("form_otp") and cfg.get("whatsapp_mode") == "cloud" and cfg.get("wa_otp_template")
                and not (store.settings or {}).get("demo"))


def send_otp(db, store: Store, cart: Cart) -> str:
    """Returns "sent", "limit" or "failed"."""
    if (cart.otp_sends or 0) >= OTP_MAX_SENDS:
        return "limit"
    code = f"{secrets.randbelow(1_000_000):06d}"
    try:
        whatsapp.cloud_send_otp(store, cart.phone, code)
    except whatsapp.CloudError:
        return "failed"
    cart.otp_hash = _hash(cart, code)
    cart.otp_expires_at = utcnow() + OTP_TTL
    cart.otp_tries = 0
    cart.otp_sends = (cart.otp_sends or 0) + 1
    cart.status = "otp"
    return "sent"


def check_otp(cart: Cart, code: str) -> str:
    """Returns "ok", "wrong", "expired" or "locked"."""
    cart.otp_tries = cart.otp_tries or 0
    if cart.otp_tries >= OTP_MAX_TRIES:
        return "locked"
    if not cart.otp_hash or not cart.otp_expires_at or as_utc(cart.otp_expires_at) < utcnow():
        return "expired"
    cart.otp_tries += 1
    code = "".join(ch for ch in str(code) if ch.isdigit())[:6]
    if hmac.compare_digest(cart.otp_hash, _hash(cart, code)):
        cart.otp_hash = ""
        return "ok"
    return "locked" if cart.otp_tries >= OTP_MAX_TRIES else "wrong"


# ---------------------------------------------------------------- abandoned carts

def abandoned(db, store: Store) -> list[Cart]:
    minutes = int(get_settings(store).get("cart_recovery_minutes") or 45)
    cutoff = utcnow() - timedelta(minutes=minutes)
    carts = db.scalars(select(Cart).where(Cart.store_id == store.id, Cart.status.in_(("open", "otp")),
                                          Cart.phone != "").order_by(Cart.updated_at.desc()).limit(300)).all()
    return [c for c in carts if as_utc(c.updated_at) <= cutoff]


def mark_recovered(db, order: Order) -> None:
    """An order from a phone that had an open cart: that cart is recovered."""
    if order.source == "form":
        return
    for cart in db.scalars(select(Cart).where(Cart.store_id == order.store_id, Cart.phone == order.phone,
                                              Cart.status.in_(("open", "otp")))):
        cart.status = "recovered"
        cart.order_id = order.id


def recovery_text(db, store: Store, cart: Cart) -> str:
    product = db.get(Product, cart.product_id) if cart.product_id else None
    template = get_settings(store).get("tpl_recovery", "")
    return notify.render_text(template, None, store, name=(cart.customer_name or "").split(" ")[0],
                              items=product.name if product else "")


def auto_recover(db) -> int:
    """Cloud mode with auto recovery on: send the recovery message once per abandoned cart."""
    sent = 0
    for store in db.scalars(select(Store)):
        cfg = get_settings(store)
        if not cfg.get("cart_auto_recovery") or cfg.get("whatsapp_mode") != "cloud":
            continue
        for cart in abandoned(db, store):
            if cart.recovery_sent_at:
                continue
            if notify.queue_to_phone(db, store, cart.phone, cart.customer_name, recovery_text(db, store, cart), "recovery"):
                sent += 1
            cart.recovery_sent_at = utcnow()
    return sent
