"""Orders from online shops: Shopify, WooCommerce and YouCan webhooks.

Each shop signs its webhook with a secret the merchant pastes into Mrigel:
  Shopify      X-Shopify-Hmac-Sha256   base64(HMAC-SHA256(secret, raw body))
  WooCommerce  X-WC-Webhook-Signature  base64(HMAC-SHA256(secret, raw body))
  YouCan       X-YOUCAN-SIGNATURE      hex(HMAC-SHA256(client secret, raw body)); body {"event_name", "data"}
The mappers turn each shop's order JSON into the dict create_order takes.
"""

import base64
import hashlib
import hmac
import re

SIGNATURE_HEADERS = {
    "shopify": "x-shopify-hmac-sha256",
    "woocommerce": "x-wc-webhook-signature",
    "youcan": "x-youcan-signature",
}
SECRET_SETTING = {"shopify": "shopify_secret", "woocommerce": "woo_secret", "youcan": "youcan_secret"}
DESK_WORDS = ("desk", "bureau", "agence", "مكتب", "stop")


def verify(shop: str, secret: str, body: bytes, header: str | None) -> bool:
    if not secret or not header:
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    expected = digest.hex() if shop == "youcan" else base64.b64encode(digest).decode()
    return hmac.compare_digest(expected.strip().lower() if shop == "youcan" else expected,
                               header.strip().lower() if shop == "youcan" else header.strip())


def _money(value) -> int:
    if isinstance(value, dict):  # Shopify price sets
        value = (value.get("shop_money") or {}).get("amount", 0)
    try:
        return max(0, round(float(str(value or 0).replace(",", "."))))
    except ValueError:
        return 0


def _wilaya(*candidates) -> str:
    for value in candidates:
        value = str(value or "").strip()
        if not value:
            continue
        match = re.fullmatch(r"(?:DZ-?)?(\d{1,2})", value, flags=re.I)
        return match.group(1) if match else value
    return ""


def _delivery_type(*labels) -> str:
    text = " ".join(str(label or "") for label in labels).lower()
    return "stopdesk" if any(word in text for word in DESK_WORDS) else "home"


def _join(*parts) -> str:
    return ", ".join(str(p).strip() for p in parts if p and str(p).strip())


def from_shopify(order: dict) -> dict:
    ship = order.get("shipping_address") or order.get("billing_address") or {}
    customer = order.get("customer") or {}
    name = ship.get("name") or _join(ship.get("first_name"), ship.get("last_name")).replace(",", "") \
        or _join(customer.get("first_name"), customer.get("last_name")).replace(",", "")
    lines = order.get("shipping_lines") or []
    return {
        "external_id": f"shopify-{order.get('name') or order.get('id')}",
        "customer_name": name,
        "phone": ship.get("phone") or order.get("phone") or customer.get("phone") or "",
        "wilaya": _wilaya(ship.get("province_code"), ship.get("province"), ship.get("city")),
        "commune": ship.get("city") or "",
        "address": _join(ship.get("address1"), ship.get("address2")),
        "items": [{"name": i.get("title") or i.get("name"), "qty": i.get("quantity"), "price": _money(i.get("price")),
                   "sku": i.get("sku") or ""} for i in order.get("line_items") or []],
        "total": _money(order.get("total_price")),
        "delivery_fee": _money(order.get("total_shipping_price_set") or sum(_money(l.get("price")) for l in lines)),
        "delivery_type": _delivery_type(*[l.get("title") for l in lines]),
        "note": order.get("note") or "",
    }


def from_woocommerce(order: dict) -> dict:
    ship, bill = order.get("shipping") or {}, order.get("billing") or {}
    pick = lambda key: ship.get(key) or bill.get(key) or ""  # noqa: E731
    lines = order.get("shipping_lines") or []
    return {
        "external_id": f"woo-{order.get('number') or order.get('id')}",
        "customer_name": _join(pick("first_name"), pick("last_name")).replace(",", ""),
        "phone": ship.get("phone") or bill.get("phone") or "",
        "wilaya": _wilaya(pick("state"), pick("city")),
        "commune": pick("city"),
        "address": _join(pick("address_1"), pick("address_2")),
        "items": [{"name": i.get("name"), "qty": i.get("quantity"), "price": _money(i.get("price")),
                   "sku": i.get("sku") or ""} for i in order.get("line_items") or []],
        "total": _money(order.get("total")),
        "delivery_fee": _money(order.get("shipping_total")),
        "delivery_type": _delivery_type(*[l.get("method_title") for l in lines]),
        "note": order.get("customer_note") or "",
    }


def from_youcan(payload: dict) -> dict:
    order = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    shipping = order.get("shipping") or {}
    address = shipping.get("address") or {}
    if isinstance(address, list):
        address = {}
    customer = order.get("customer") or {}
    items = []
    for line in order.get("variants") or []:
        variant = line.get("variant") or {}
        product = variant.get("product") or {}
        items.append({"name": product.get("name") or variant.get("name") or "", "qty": line.get("quantity"),
                      "price": _money(line.get("price")), "sku": variant.get("sku") or ""})
    return {
        "external_id": f"youcan-{order.get('ref') or order.get('id')}",
        "customer_name": address.get("full_name") or _join(address.get("first_name"), address.get("last_name")).replace(",", "")
        or _join(customer.get("first_name"), customer.get("last_name")).replace(",", ""),
        "phone": address.get("phone") or customer.get("phone") or "",
        "wilaya": _wilaya(address.get("region"), address.get("city")),
        "commune": address.get("city") or "",
        "address": _join(address.get("first_line"), address.get("second_line")),
        "items": items,
        "total": _money(order.get("total")),
        "delivery_fee": _money(shipping.get("price")),
        "delivery_type": _delivery_type(shipping.get("name"), shipping.get("method")),
        "note": order.get("note") or "",
    }


MAPPERS = {"shopify": from_shopify, "woocommerce": from_woocommerce, "youcan": from_youcan}
ORDER_TOPICS = {
    "shopify": ("orders/create",),
    "woocommerce": ("order.created",),
    "youcan": ("order.created", "order.create"),
}
TOPIC_HEADERS = {"shopify": "x-shopify-topic", "woocommerce": "x-wc-webhook-topic", "youcan": "x-youcan-topic"}
