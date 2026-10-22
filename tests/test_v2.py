"""Tests for products and stock, delivery updates, automations, COD reconciliation, the order form,
OTP, abandoned carts, shop webhooks, the inbox, campaigns, saved views and the installable app."""

import base64
import hashlib
import hmac
import io
import json
import re
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app import whatsapp
from app.db import SessionLocal
from app.jobs import run_followups
from app.models import (BlacklistEntry, Campaign, Cart, Contact, Message, Order, Payout, Product, Rule, SavedView,
                        StockMove, Store, utcnow)
from app.i18n import T
from app.store_settings import get_settings, update_settings

from .conftest import make_client, new_order


def _get(model, row_id):
    with SessionLocal() as db:
        row = db.get(model, row_id)
        db.expunge(row)
        return row


def _store() -> Store:
    with SessionLocal() as db:
        store = db.scalars(select(Store)).first()
        db.expunge(store)
        return store


def _set(**changes):
    with SessionLocal() as db:
        store = db.scalars(select(Store)).first()
        update_settings(store, changes)
        db.commit()


def _product(owner, **values) -> str:
    data = {"name": "Crème", "sku": "CR-01", "price_dzd": "2500", "cost_dzd": "900", "stock": "10",
            "low_stock": "2", "track_stock": "on", "form_enabled": "on", "delivery_fee_dzd": "400"}
    data.update(values)
    response = owner.post_form("/products/new", data, from_page="/products/new", follow_redirects=False)
    assert response.status_code == 303, response.text[:400]
    return response.headers["location"].rsplit("/", 1)[-1]


def _stage(owner, order_id, stage, **extra):
    response = owner.post_form(f"/orders/{order_id}/stage", {"stage": stage, **extra}, follow_redirects=False)
    assert response.status_code == 303


@pytest.fixture
def cloud_calls(monkeypatch):
    """Capture what would go to Meta instead of calling it."""
    calls = []

    def fake_post(cfg, payload):
        calls.append(payload)
        return f"wamid.out{len(calls)}"

    monkeypatch.setattr(whatsapp, "_cloud_post", fake_post)
    return calls


def _cloud(owner, secret="app-secret"):
    owner.post_form("/settings", {"store_name": "Boutique Test", "whatsapp_mode": "cloud", "wa_phone_number_id": "PNID",
                                  "wa_app_secret": secret, "wa_verify_token": "verify-me", "wa_access_token": "tok"},
                    from_page="/settings")


# ================================================================ products and stock

def test_stock_follows_the_order(owner):
    product_id = _product(owner)
    order_id = new_order(owner, product="crème", qty="3")  # matched by name, case and accents as typed
    order = _get(Order, order_id)
    assert order.items[0]["product_id"] == product_id and order.items[0]["sku"] == "CR-01"
    _stage(owner, order_id, "confirmed")
    assert _get(Product, product_id).stock == 7
    _stage(owner, order_id, "confirmed")  # same stage twice: no double move
    assert _get(Product, product_id).stock == 7
    _stage(owner, order_id, "cancelled")
    assert _get(Product, product_id).stock == 10
    _stage(owner, order_id, "new")
    _stage(owner, order_id, "confirmed")
    _stage(owner, order_id, "shipped")
    _stage(owner, order_id, "returned")
    assert _get(Product, product_id).stock == 10
    with SessionLocal() as db:
        reasons = [m.reason for m in db.scalars(select(StockMove).order_by(StockMove.created_at))]
    assert reasons == ["initial", "confirmed", "released", "confirmed", "returned"]


def test_stock_adjust_and_low_stock_alert(owner):
    product_id = _product(owner, stock="3")
    owner.post_form(f"/products/{product_id}/stock", {"delta": "-2"}, from_page=f"/products/{product_id}")
    assert _get(Product, product_id).stock == 1
    page = owner.get("/dashboard")
    assert page.status_code == 200
    new_order(owner, product="Crème")
    assert "مخزون قليل" in owner.get("/dashboard").text


def test_product_validation(owner):
    _product(owner)
    response = owner.post_form("/products/new", {"name": "Autre", "sku": "CR-01"}, from_page="/products/new")
    assert response.status_code == 400
    assert "مستعمل" in response.text


def test_per_product_and_per_agent_numbers(owner):
    from app.stats import dashboard

    _product(owner)
    for _ in range(3):
        order_id = new_order(owner, product="Crème")
        _stage(owner, order_id, "confirmed")
        _stage(owner, order_id, "shipped")
    _stage(owner, order_id, "returned")
    cancelled = new_order(owner, product="Sérum")
    _stage(owner, cancelled, "cancelled")
    with SessionLocal() as db:
        stats = dashboard(db, db.scalars(select(Store)).first(), 30)
    creme = next(p for p in stats["products"] if p["name"] == "Crème")
    assert creme["orders"] == 3 and creme["confirm_rate"] == 100 and creme["returned"] == 1
    assert creme["return_rate"] == 100  # 1 returned, 0 delivered yet
    serum = next(p for p in stats["products"] if p["name"] == "Sérum")
    assert serum["product_id"] is None and serum["cancelled"] == 1
    agent = stats["agents"][0]
    assert agent["confirmed"] == 3 and agent["cancelled"] == 1 and agent["confirm_rate"] == 75
    assert agent["median_minutes"] is not None and agent["delivery_rate"] == 0


# ================================================================ delivery updates to the buyer

def test_assisted_shipping_notice_waits_for_one_tap(owner):
    order_id = new_order(owner)
    _stage(owner, order_id, "confirmed")
    owner.post_form(f"/orders/{order_id}/shipping", {"carrier": "yalidine", "tracking": "YAL-123"})
    _stage(owner, order_id, "shipped")
    with SessionLocal() as db:
        notice = db.scalars(select(Message).where(Message.order_id == order_id, Message.kind == "notify")).one()
        assert notice.status == "todo" and "YAL-123" in notice.text and "Yalidine" in notice.text
        notice_id = notice.id
    page = owner.get(f"/orders/{order_id}")
    assert "تستنى تبعثها" in page.text
    response = owner.post_form(f"/messages/{notice_id}/open", {}, from_page=f"/orders/{order_id}",
                               follow_redirects=False)
    assert response.headers["location"].startswith("https://wa.me/213555123456?text=")
    assert _get(Message, notice_id).status == "opened"
    # out for delivery
    owner.post_form(f"/orders/{order_id}/out", {}, from_page=f"/orders/{order_id}")
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Message).where(Message.kind == "notify")) == 2


def test_cloud_notices_are_sent_by_the_job(owner, cloud_calls):
    _cloud(owner)
    order_id = new_order(owner)
    _stage(owner, order_id, "confirmed")
    _stage(owner, order_id, "shipped")
    _stage(owner, order_id, "delivered")
    with SessionLocal() as db:
        statuses = [m.status for m in db.scalars(select(Message).where(Message.kind == "notify"))]
    assert statuses == ["queued", "queued"]
    result = run_followups()
    assert result["sent"] == 2 and len(cloud_calls) == 2
    assert cloud_calls[0]["type"] == "text"  # no template configured: plain text
    # outside the 24 h window with a template configured, the template is used
    _set(wa_notify_template="order_update")
    order_2 = new_order(owner, phone="0661223344")
    _stage(owner, order_2, "confirmed")
    _stage(owner, order_2, "shipped")
    run_followups()
    assert cloud_calls[-1]["type"] == "template" and cloud_calls[-1]["template"]["name"] == "order_update"


def test_notices_can_be_turned_off(owner):
    owner.post_form("/settings", {"bool:notify_shipped": "1", "bool:notify_delivered": "1"}, from_page="/settings")
    assert get_settings(_store())["notify_shipped"] is False
    assert get_settings(_store())["ai_enabled"] is True  # a checkbox not on the form keeps its value
    order_id = new_order(owner)
    _stage(owner, order_id, "confirmed")
    _stage(owner, order_id, "shipped")
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Message).where(Message.kind == "notify")) == 0


# ================================================================ automations

def test_rule_builder_tags_and_assigns(owner):
    response = owner.post_form("/automations", {
        "name": "Risky Algiers", "event": "order_created",
        "cond_field_0": "wilaya_code", "cond_op_0": "in", "cond_value_0": "16, 31",
        "cond_field_1": "total_dzd", "cond_op_1": "gte", "cond_value_1": "2000",
        "act_type_0": "tag", "act_value_0": "algiers",
        "act_type_1": "note", "act_value_1": "call first",
    }, from_page="/automations", follow_redirects=False)
    assert response.status_code == 303
    tagged = new_order(owner, wilaya="16", total="2500")
    not_tagged = new_order(owner, wilaya="5", total="2500", phone="0661 00 11 22")
    assert _get(Order, tagged).tags == ["algiers"]
    assert _get(Order, not_tagged).tags == []
    with SessionLocal() as db:
        assert db.scalars(select(Rule)).one().runs == 1
    assert "call first" in owner.get(f"/orders/{tagged}").text
    # tag filter on the orders list
    page = owner.get("/orders?tag=algiers")
    assert tagged in page.text and not_tagged not in page.text


def test_rule_template_blacklists_on_return(owner):
    owner.post_form("/automations/template/blacklist_on_return", {}, from_page="/automations")
    order_id = new_order(owner)
    for stage in ("confirmed", "shipped", "returned"):
        _stage(owner, order_id, stage)
    with SessionLocal() as db:
        assert db.scalar(select(BlacklistEntry.phone)) == "0555123456"


def test_rules_cannot_loop_forever(owner):
    with SessionLocal() as db:
        store = db.scalars(select(Store)).first()
        db.add(Rule(store_id=store.id, name="a", event="stage_changed",
                    conditions=[{"field": "stage", "op": "eq", "value": "confirmed"}],
                    actions=[{"type": "set_stage", "value": "pending"}]))
        db.add(Rule(store_id=store.id, name="b", event="stage_changed",
                    conditions=[{"field": "stage", "op": "eq", "value": "pending"}],
                    actions=[{"type": "set_stage", "value": "confirmed"}]))
        db.commit()
    order_id = new_order(owner)
    _stage(owner, order_id, "confirmed")  # would ping-pong without the depth guard
    assert _get(Order, order_id).stage in ("confirmed", "pending")


def test_rule_matching_unit():
    from app.rules import matches

    order = Order(risk_score=70, total_dzd=1000, wilaya_code=16, source="form", tags=["VIP"], phone_valid=False,
                  items=[{"name": "Sérum éclat", "sku": "SR-1"}])
    assert matches(order, {"field": "risk_score", "op": "gte", "value": "60"})
    assert not matches(order, {"field": "risk_score", "op": "lte", "value": "60"})
    assert matches(order, {"field": "wilaya_code", "op": "not_in", "value": "1,2"})
    assert matches(order, {"field": "tags", "op": "contains", "value": "vip"})
    assert matches(order, {"field": "phone_valid", "op": "eq", "value": "false"})
    assert matches(order, {"field": "product", "op": "contains", "value": "sr-1"})
    assert not matches(order, {"field": "password", "op": "eq", "value": "x"})


# ================================================================ COD reconciliation and statement

def _shipped(owner, tracking, **overrides):
    order_id = new_order(owner, **overrides)
    _stage(owner, order_id, "confirmed")
    owner.post_form(f"/orders/{order_id}/shipping", {"carrier": "yalidine", "tracking": tracking})
    _stage(owner, order_id, "shipped")
    return order_id


def test_payout_reconciliation(owner):
    first = _shipped(owner, "YAL-1")
    second = _shipped(owner, "YAL-2", phone="0661223344", total="4000")
    csv = ("Etat des paiements\n"
           "Tracking;Montant encaissé;Frais de livraison\n"
           "YAL-1;2 500,00;400\n"
           "YAL-2;3 500;400\n"
           "YAL-999;1000;400\n").encode("utf-8")
    response = owner.post("/finance/payout", data={"csrf": owner.csrf("/finance"), "carrier": "yalidine"},
                          files={"file": ("paiement.csv", io.BytesIO(csv), "text/csv")}, follow_redirects=False)
    assert response.status_code == 303
    payout = _get(Payout, response.headers["location"].rsplit("/", 1)[-1])
    assert payout.rows == 3 and payout.matched == 2
    assert payout.collected_dzd == 6000 and payout.fees_dzd == 800
    assert sorted(i["kind"] for i in payout.issues) == ["amount_mismatch", "not_found"]
    for order_id in (first, second):
        order = _get(Order, order_id)
        assert order.stage == "delivered" and order.paid_at is not None
    report = owner.get(response.headers["location"])
    assert "YAL-999" in report.text
    # the same file again: already paid
    again = owner.post("/finance/payout", data={"csrf": owner.csrf("/finance"), "carrier": "yalidine"},
                       files={"file": ("paiement.csv", io.BytesIO(csv), "text/csv")}, follow_redirects=False)
    payout_2 = _get(Payout, again.headers["location"].rsplit("/", 1)[-1])
    assert payout_2.matched == 0 and sum(1 for i in payout_2.issues if i["kind"] == "already_paid") == 2


def test_payout_xlsx_and_late_payments(owner):
    from openpyxl import Workbook

    order_id = _shipped(owner, "ZR-77")
    late = _shipped(owner, "ZR-78", phone="0661223344")
    _stage(owner, late, "delivered")
    with SessionLocal() as db:
        db.get(Order, late).closed_at = utcnow() - timedelta(days=12)
        db.commit()
    book = Workbook()
    sheet = book.active
    sheet.append(["N° suivi", "Montant", "Frais"])
    sheet.append(["ZR-77", 2500, 350])
    data = io.BytesIO()
    book.save(data)
    owner.post("/finance/payout", data={"csrf": owner.csrf("/finance"), "carrier": "zr"},
               files={"file": ("zr.xlsx", io.BytesIO(data.getvalue()), "application/octet-stream")})
    assert _get(Order, order_id).cod_collected_dzd == 2500
    page = owner.get("/finance")
    assert page.status_code == 200 and "ZR-78" in page.text  # delivered 12 days ago and never paid


def test_payout_without_columns(owner):
    response = owner.post("/finance/payout", data={"csrf": owner.csrf("/finance")},
                          files={"file": ("x.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")})
    assert "ما لقيناش" in response.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Payout)) == 0


def test_monthly_statement_pdf(owner):
    order_id = _shipped(owner, "YAL-5")
    _stage(owner, order_id, "delivered")
    month = utcnow().strftime("%Y-%m")
    response = owner.get(f"/finance/statement?month={month}")
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    assert response.headers["content-type"] == "application/pdf"
    assert owner.get("/finance/statement?month=2026-13").status_code == 404


def test_money_pages_are_owner_only(owner):
    owner.post_form("/team", {"name": "Agent", "email": "agent@test.dz", "password": "password123", "role": "agent"},
                    from_page="/team")
    agent = make_client()
    agent.post("/login", data={"csrf": agent.csrf("/login"), "email": "agent@test.dz", "password": "password123"})
    for path in ("/finance", "/automations", "/integrations", "/products/new"):
        assert agent.get(path).status_code == 403, path
    for path in ("/inbox", "/carts", "/products", "/campaigns"):
        assert agent.get(path).status_code == 200, path


# ================================================================ order form, abandoned carts, OTP

def _form_token(client, product_id):
    page = client.get(f"/f/{product_id}")
    assert page.status_code == 200
    return re.search(r'name="token" value="([^"]+)"', page.text).group(1)


BUYER = {"customer_name": "Yacine Haddad", "phone": "0770112233", "wilaya": "31", "commune": "Bir El Djir",
         "address": "Cité USTO", "delivery_type": "home", "qty": "2"}


def test_order_form_creates_order_with_upsell(owner):
    upsell_id = _product(owner, name="Savon", sku="SV-1", price_dzd="800", stock="5")
    product_id = _product(owner, sku="CR-02", upsell_product_id=upsell_id, upsell_price_dzd="500")
    buyer = make_client()
    page = buyer.get(f"/f/{product_id}")
    assert "X-Frame-Options" not in page.headers and "frame-ancestors *" in page.headers["content-security-policy"]
    assert "Savon" in page.text
    token = _form_token(buyer, product_id)
    response = buyer.post(f"/f/{product_id}", data={**BUYER, "token": token, "upsell": "1"})
    assert response.status_code == 200 and "وصلتنا طلبيتك" in response.text
    with SessionLocal() as db:
        order = db.scalars(select(Order)).one()
        assert order.source == "form" and order.wilaya_code == 31 and order.phone == "0770112233"
        assert order.total_dzd == 2500 * 2 + 500 + 400 and order.delivery_fee_dzd == 400
        assert [i["product_id"] for i in order.items] == [product_id, upsell_id]
        assert order.tags == ["upsell"]
        assert db.scalars(select(Cart)).one().status == "ordered"
    # the same token again does not create a second order
    buyer.post(f"/f/{product_id}", data={**BUYER, "token": token})
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 1


def test_order_form_validation_and_token(owner):
    product_id = _product(owner)
    buyer = make_client()
    token = _form_token(buyer, product_id)
    bad = buyer.post(f"/f/{product_id}", data={**BUYER, "phone": "021 12 34 56", "wilaya": "", "token": token})
    assert bad.status_code == 400 and "05، 06 ولا 07" in bad.text and "اختار الولاية" in bad.text
    forged = buyer.post(f"/f/{product_id}", data={**BUYER, "token": "forged"})
    assert forged.status_code == 400
    other = _product(owner, sku="OTHER")
    wrong_product = buyer.post(f"/f/{other}", data={**BUYER, "token": token})
    assert wrong_product.status_code == 400  # a token only works for its own product
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 0
    # disabled form
    owner.post_form(f"/products/{product_id}", {"name": "Crème", "sku": "CR-01", "active": "on"},
                    from_page=f"/products/{product_id}")
    assert buyer.get(f"/f/{product_id}").status_code == 404


def test_abandoned_cart_recovery(owner):
    product_id = _product(owner)
    buyer = make_client()
    token = _form_token(buyer, product_id)
    assert buyer.post(f"/f/{product_id}/draft", data={"token": token, "phone": "07"}).status_code == 204
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Cart)) == 0  # no phone yet, nothing kept
    buyer.post(f"/f/{product_id}/draft", data={"token": token, "customer_name": "Yacine", "phone": "0770112233",
                                               "wilaya": "31", "qty": "1"})
    assert "0770112233" not in owner.get("/carts").text  # too fresh to be abandoned
    with SessionLocal() as db:
        cart = db.scalars(select(Cart)).one()
        cart.updated_at = utcnow() - timedelta(hours=2)
        db.commit()
        cart_id = cart.id
    page = owner.get("/carts")
    assert "0770112233" in page.text and "وهران" in page.text
    response = owner.post_form(f"/carts/{cart_id}/recover", {}, from_page="/carts", follow_redirects=False)
    assert response.headers["location"].startswith("https://wa.me/213770112233?text=")
    assert _get(Cart, cart_id).recovery_sent_at is not None
    # the buyer said yes on WhatsApp: one click makes the order
    response = owner.post_form(f"/carts/{cart_id}/order", {}, from_page="/carts", follow_redirects=False)
    order = _get(Order, response.headers["location"].rsplit("/", 1)[-1])
    assert order.source == "form" and order.wilaya_code == 31
    assert _get(Cart, cart_id).status == "recovered"


def test_cart_recovered_by_a_manual_order(owner):
    product_id = _product(owner)
    buyer = make_client()
    token = _form_token(buyer, product_id)
    buyer.post(f"/f/{product_id}/draft", data={"token": token, "customer_name": "Amina", "phone": "0555123456"})
    new_order(owner)  # same phone, typed by an agent after a call
    with SessionLocal() as db:
        assert db.scalars(select(Cart)).one().status == "recovered"


def test_order_form_with_whatsapp_code(owner, cloud_calls):
    _cloud(owner)
    owner.post_form("/settings", {"next": "/integrations", "bool:form_otp": "1", "form_otp": "on",
                                  "wa_otp_template": "otp_code"}, from_page="/integrations")
    product_id = _product(owner)
    buyer = make_client()
    token = _form_token(buyer, product_id)
    step = buyer.post(f"/f/{product_id}", data={**BUYER, "token": token})
    assert "أكّد رقمك" in step.text
    code = cloud_calls[-1]["template"]["components"][0]["parameters"][0]["text"]
    assert cloud_calls[-1]["template"]["name"] == "otp_code" and len(code) == 6
    wrong = "000000" if code != "000000" else "111111"
    assert buyer.post(f"/f/{product_id}/otp", data={"token": token, "code": wrong}).status_code == 400
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 0
        assert db.scalars(select(Cart)).one().otp_hash != code  # stored hashed
    done = buyer.post(f"/f/{product_id}/otp", data={"token": token, "code": code})
    assert done.status_code == 200 and "وصلتنا طلبيتك" in done.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 1


def test_otp_locks_after_five_tries():
    from app.storefront import _hash, check_otp

    cart = Cart(id="c1", otp_tries=0, otp_expires_at=utcnow() + timedelta(minutes=5))
    cart.otp_hash = _hash(cart, "123456")
    results = [check_otp(cart, "999999") for _ in range(5)]
    assert results[-1] == "locked" and check_otp(cart, "123456") == "locked"
    expired = Cart(id="c2", otp_tries=0, otp_expires_at=utcnow() - timedelta(minutes=1))
    expired.otp_hash = _hash(expired, "123456")
    assert check_otp(expired, "123456") == "expired"


# ================================================================ Shopify, WooCommerce, YouCan

SHOPIFY_ORDER = {
    "id": 820982911946154508, "name": "#1001", "total_price": "5400.00", "note": "Appeler avant",
    "shipping_address": {"first_name": "Sara", "last_name": "Kaci", "name": "Sara Kaci", "phone": "+213 661 23 45 67",
                         "address1": "12 rue Didouche", "city": "Alger Centre", "province": "Alger"},
    "line_items": [{"title": "Crème", "quantity": 2, "price": "2500.00", "sku": "CR-01"}],
    "shipping_lines": [{"title": "Stop desk Yalidine", "price": "400.00"}],
    "total_shipping_price_set": {"shop_money": {"amount": "400.00", "currency_code": "DZD"}},
}


def _shopify_headers(body: bytes, secret="shp-secret"):
    digest = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    return {"X-Shopify-Hmac-Sha256": digest, "X-Shopify-Topic": "orders/create", "Content-Type": "application/json"}


def test_shopify_webhook(owner):
    product_id = _product(owner)
    owner.post_form("/settings", {"next": "/integrations", "shopify_secret": "shp-secret"}, from_page="/integrations")
    store = _store()
    assert store.settings["shopify_secret"].startswith("enc:")
    body = json.dumps(SHOPIFY_ORDER).encode()
    url = f"/webhooks/shop/shopify/{store.id}"
    assert owner.post(url, content=body, headers=_shopify_headers(body, "wrong")).status_code == 401
    response = owner.post(url, content=body, headers=_shopify_headers(body))
    assert response.status_code == 201
    order = _get(Order, response.json()["id"])
    assert order.external_id == "shopify-#1001" and order.source == "shopify"
    assert order.customer_name == "Sara Kaci" and order.phone == "0661234567" and order.wilaya_code == 16
    assert order.total_dzd == 5400 and order.delivery_fee_dzd == 400 and order.delivery_type == "stopdesk"
    assert order.items[0]["product_id"] == product_id and order.note == "Appeler avant"
    again = owner.post(url, content=body, headers=_shopify_headers(body))
    assert again.json()["duplicate"] is True
    other_topic = owner.post(url, content=body, headers={**_shopify_headers(body), "X-Shopify-Topic": "orders/paid"})
    assert other_topic.json()["ignored"] == "orders/paid"


def test_woocommerce_webhook(owner):
    owner.post_form("/settings", {"next": "/integrations", "woo_secret": "woo-secret"}, from_page="/integrations")
    store = _store()
    url = f"/webhooks/shop/woocommerce/{store.id}"
    ping = owner.post(url, content=b"webhook_id=12", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert ping.json()["ping"] is True
    payload = {"id": 727, "number": "727", "total": "3900.00", "shipping_total": "400.00", "customer_note": "",
               "billing": {"first_name": "Nadia", "last_name": "Mansouri", "phone": "0550 99 88 77", "state": "DZ-31",
                           "city": "Oran", "address_1": "Hai Sabah"},
               "shipping": {"first_name": "", "last_name": "", "state": "", "city": "", "address_1": ""},
               "line_items": [{"name": "Sérum", "quantity": 1, "price": 3500, "sku": ""}],
               "shipping_lines": [{"method_title": "Livraison à domicile"}]}
    body = json.dumps(payload).encode()
    signature = base64.b64encode(hmac.new(b"woo-secret", body, hashlib.sha256).digest()).decode()
    response = owner.post(url, content=body, headers={"X-WC-Webhook-Signature": signature,
                                                      "X-WC-Webhook-Topic": "order.created"})
    assert response.status_code == 201
    order = _get(Order, response.json()["id"])
    assert order.customer_name == "Nadia Mansouri" and order.wilaya_code == 31 and order.delivery_type == "home"
    assert order.total_dzd == 3900 and order.external_id == "woo-727"


def test_youcan_webhook(owner):
    owner.post_form("/settings", {"next": "/integrations", "youcan_secret": "yc-secret"}, from_page="/integrations")
    store = _store()
    payload = {"event_name": "order.created", "event_happened_at": "2026-10-22T10:00:00Z", "data": {
        "id": "abc", "ref": "046", "total": 2900,
        "shipping": {"price": 400, "address": {"full_name": "Karim Ziani", "phone": "+213770445566",
                                               "first_line": "Cité 1000 logements", "city": "Sétif", "region": "Sétif"}},
        "variants": [{"price": 2500, "quantity": 1, "variant": {"sku": None, "product": {"name": "Parfum"}}}]}}
    body = json.dumps(payload).encode()
    signature = hmac.new(b"yc-secret", body, hashlib.sha256).hexdigest()
    response = owner.post(f"/webhooks/shop/youcan/{store.id}", content=body,
                          headers={"X-YOUCAN-SIGNATURE": signature, "Content-Type": "application/json"})
    assert response.status_code == 201
    order = _get(Order, response.json()["id"])
    assert order.customer_name == "Karim Ziani" and order.phone == "0770445566" and order.wilaya_code == 19
    assert order.items[0]["name"] == "Parfum" and order.external_id == "youcan-046"
    assert owner.post(f"/webhooks/shop/nope/{store.id}", content=body).status_code == 404


# ================================================================ inbox

def _wa_payload(text, sender="213661000111", msg_id="wamid.in1", name="Lamia"):
    return {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "PNID"},
                                              "contacts": [{"wa_id": sender, "profile": {"name": name}}],
                                              "messages": [{"from": sender, "id": msg_id, "type": "text",
                                                            "text": {"body": text}}]}}]}]}


def _sig(body, secret="app-secret"):
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(),
            "Content-Type": "application/json"}


def test_inbox_keeps_messages_from_new_buyers(owner, cloud_calls):
    _cloud(owner)
    body = json.dumps(_wa_payload("salam, ch7al prix crème?")).encode()
    assert owner.post("/webhooks/whatsapp", content=body, headers=_sig(body)).json()["handled"] == 1
    with SessionLocal() as db:
        contact = db.scalars(select(Contact)).one()
        assert contact.handle == "0661000111" and contact.name == "Lamia" and contact.unread == 1
        contact_id = contact.id
    assert '<span class="count num">1</span>' in owner.get("/dashboard").text  # unread badge on the menu
    page = owner.get(f"/inbox?c={contact_id}")
    assert "ch7al prix" in page.text
    assert _get(Contact, contact_id).unread == 0  # opening the conversation marks it read
    owner.post_form(f"/inbox/{contact_id}/reply", {"text": "2500 دج"}, from_page=f"/inbox?c={contact_id}")
    assert cloud_calls[-1]["text"]["body"] == "2500 دج"  # inside the 24 h window: free text
    # STOP opts the contact out of campaigns
    stop = json.dumps(_wa_payload("STOP", msg_id="wamid.in2")).encode()
    owner.post("/webhooks/whatsapp", content=stop, headers=_sig(stop))
    assert _get(Contact, contact_id).opted_out is True


def test_inbox_assisted_reply_opens_whatsapp(owner):
    order_id = new_order(owner)
    owner.post_form(f"/orders/{order_id}/wa", {}, follow_redirects=False)
    with SessionLocal() as db:
        contact_id = db.scalars(select(Contact)).one().id
    response = owner.post_form(f"/inbox/{contact_id}/reply", {"text": "Merci"}, from_page="/inbox",
                               follow_redirects=False)
    assert response.headers["location"].startswith("https://wa.me/213555123456?text=Merci")
    page = owner.get(f"/inbox?c={contact_id}")
    assert "Amina" in page.text and order_id in page.text  # the buyer's orders are shown next to the chat


def test_messenger_and_instagram_webhook(owner, monkeypatch):
    _cloud(owner)
    owner.post_form("/settings", {"next": "/integrations", "fb_page_id": "PAGE1", "fb_page_token": "page-token",
                                  "ig_account_id": "IG1"}, from_page="/integrations")
    sent = []
    import httpx

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"message_id": "m.1"}

    monkeypatch.setattr(httpx, "post", lambda url, json=None, headers=None, timeout=None: sent.append((url, json)) or FakeResponse())
    payload = {"object": "instagram", "entry": [{"id": "IG1", "messaging": [
        {"sender": {"id": "IGSID9"}, "recipient": {"id": "IG1"}, "message": {"mid": "mid.1", "text": "prix?"}},
        {"sender": {"id": "IG1"}, "recipient": {"id": "IGSID9"}, "message": {"mid": "mid.2", "text": "echo", "is_echo": True}},
    ]}]}
    body = json.dumps(payload).encode()
    assert owner.post("/webhooks/meta", content=body, headers=_sig(body, "forged")).status_code == 401
    assert owner.post("/webhooks/meta", content=body, headers=_sig(body)).json()["handled"] == 1
    with SessionLocal() as db:
        contact = db.scalars(select(Contact)).one()
        assert contact.channel == "instagram" and contact.handle == "IGSID9"
        contact_id = contact.id
    owner.post_form(f"/inbox/{contact_id}/reply", {"text": "3000 DA"}, from_page="/inbox")
    url, payload = sent[-1]
    assert url.endswith("/PAGE1/messages") and payload["recipient"]["id"] == "IGSID9"
    verify = owner.get("/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                                 "hub.challenge": "42"})
    assert verify.text == "42"


# ================================================================ campaigns

def test_campaign_audience_and_assisted_sending(owner):
    for phone in ("0555123456", "0661223344", "0770556677"):
        order_id = new_order(owner, phone=phone)
        for stage in ("confirmed", "shipped", "delivered"):
            _stage(owner, order_id, stage)
    new_order(owner, phone="0555123456")  # same buyer twice: one message
    owner.post_form("/blacklist", {"phone": "0661223344"}, from_page="/blacklist")
    with SessionLocal() as db:
        contact = db.scalar(select(Contact).where(Contact.handle == "0770556677"))
        contact.opted_out = True
        db.commit()
    response = owner.post_form("/campaigns", {"name": "Aïd", "text": "Saha 3idkoum {name} من {store}",
                                              "stages": "delivered", "days": "0"}, from_page="/campaigns",
                               follow_redirects=False)
    campaign = _get(Campaign, response.headers["location"].rsplit("/", 1)[-1])
    assert [r["phone"] for r in campaign.recipients] == ["0555123456"]
    opened = owner.post_form(f"/campaigns/{campaign.id}/open", {"phone": "0555123456"},
                             from_page=f"/campaigns/{campaign.id}", follow_redirects=False)
    assert opened.headers["location"].startswith("https://wa.me/213555123456?text=Saha")
    campaign = _get(Campaign, campaign.id)
    assert campaign.status == "done" and campaign.recipients[0]["status"] == "sent"


def test_campaign_cloud_queue(owner, cloud_calls):
    _cloud(owner)
    _set(wa_campaign_template="promo")
    order_id = new_order(owner)
    for stage in ("confirmed", "shipped", "delivered"):
        _stage(owner, order_id, stage)
    run_followups()  # sends the shipping and delivery notices
    before = len(cloud_calls)
    response = owner.post_form("/campaigns", {"name": "Promo", "text": "Promo {name}", "stages": "delivered"},
                               from_page="/campaigns", follow_redirects=False)
    campaign_id = response.headers["location"].rsplit("/", 1)[-1]
    owner.post_form(f"/campaigns/{campaign_id}/send", {}, from_page=f"/campaigns/{campaign_id}")
    run_followups()
    assert len(cloud_calls) == before + 1
    assert cloud_calls[-1]["template"]["name"] == "promo"
    assert cloud_calls[-1]["template"]["components"][0]["parameters"][0]["text"] == "Promo Amina"


# ================================================================ saved views, dashboard layout, app

def test_saved_views_and_filters(owner):
    risky = new_order(owner, phone="021 12 34 56")  # landline: higher risk
    owner.post_form("/views", {"name": "Risky", "query": "risk=high&source=manual&evil=1"}, from_page="/orders")
    with SessionLocal() as db:
        view = db.scalars(select(SavedView)).one()
        assert view.query == "source=manual&risk=high" or view.query == "risk=high&source=manual"
    page = owner.get("/orders")
    assert "Risky" in page.text
    assert owner.get("/orders?source=api").text.count(risky) == 0
    owner.post_form(f"/views/{view.id}/delete", {}, from_page="/orders")
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SavedView)) == 0


def test_dashboard_layout(owner):
    new_order(owner)
    owner.post_form("/dashboard/layout", {"show_chart": "on", "show_funnel": "on", "days": "7"}, from_page="/dashboard")
    page = owner.get("/dashboard")
    main = page.text.split("<main")[1]
    assert T["chart_orders_day"]["ar"] in main
    assert f'<h2>{T["agents_title"]["ar"]}</h2>' not in main and f'<h2>{T["wilaya_title"]["ar"]}</h2>' not in main
    assert f'<h2>{T["chart_orders_day"]["ar"]}</h2>' in main
    assert 'href="/dashboard?days=7" aria-current="true"' in page.text


def test_installable_app(client):
    assert client.get("/sw.js").headers["content-type"].startswith("application/javascript")
    manifest = client.get("/manifest.webmanifest")
    assert manifest.json()["start_url"] == "/queue"
    assert client.get("/offline").status_code == 200
    assert client.get("/static/icon-192.png").status_code == 200


def test_new_pages_render(owner):
    product_id = _product(owner)
    new_order(owner)
    for path in ("/products", f"/products/{product_id}", "/finance", "/automations", "/inbox", "/campaigns",
                 "/carts", "/integrations", "/settings", "/dashboard", "/orders"):
        assert owner.get(path).status_code == 200, path
    owner.get("/lang/fr")
    for path in ("/products", "/finance", "/automations", "/inbox", "/campaigns", "/carts", "/integrations"):
        page = owner.get(path)
        assert page.status_code == 200 and 'dir="ltr"' in page.text, path


def test_old_database_gets_new_columns(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, inspect, text

    from app import db as db_module

    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE stores (id VARCHAR(36) PRIMARY KEY, name VARCHAR(120))"))
    monkeypatch.setattr(db_module, "engine", engine)
    added = db_module.add_missing_columns()
    assert "stores.api_key" in added and "stores.settings" in added
    assert "api_key" in {c["name"] for c in inspect(engine).get_columns("stores")}
    assert db_module.add_missing_columns() == []
