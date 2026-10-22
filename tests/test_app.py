import hashlib
import hmac
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from sqlalchemy import func, select

from app.db import SessionLocal
from app.jobs import run_followups
from app.models import BlacklistEntry, Message, Order, Store, User, utcnow
from app.security import hash_password

from .conftest import make_client, new_order, signup


def _order(order_id: str) -> Order:
    with SessionLocal() as db:
        order = db.get(Order, order_id)
        db.expunge(order)
        return order


def _store() -> Store:
    with SessionLocal() as db:
        return db.scalars(select(Store)).first()


# ---------------------------------------------------------------- accounts

def test_signup_and_empty_dashboard(client):
    signup(client)
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "مازال ما كاين حتى طلبية" in page.text  # empty state
    client.post_form("/logout", {}, follow_redirects=False)
    assert client.get("/dashboard", follow_redirects=False).headers["location"] == "/login"
    response = client.post("/login", data={"csrf": client.csrf("/login"), "email": "OWNER@test.dz",
                                           "password": "password123"}, follow_redirects=False)
    assert response.headers["location"] == "/dashboard"


def test_login_wrong_password(client):
    signup(client)
    client.post_form("/logout", {}, follow_redirects=False)
    response = client.post("/login", data={"csrf": client.csrf("/login"), "email": "owner@test.dz", "password": "nope-nope"})
    assert response.status_code == 400
    assert "غالطين" in response.text


def test_signup_validation(client):
    response = client.post("/signup", data={"csrf": client.csrf("/signup"), "store_name": "S", "name": "N",
                                            "email": "a@b.dz", "password": "short"})
    assert response.status_code == 400
    signup(client)
    other = make_client()
    response = other.post("/signup", data={"csrf": other.csrf("/signup"), "store_name": "S", "name": "N",
                                           "email": "owner@test.dz", "password": "password123"})
    assert response.status_code == 400  # email taken


def test_csrf_required(owner):
    response = owner.post("/orders/new", data={"customer_name": "X", "phone": "0555123456"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/dashboard"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 0


def test_login_rate_limit(client):
    signup(client)
    client.post_form("/logout", {}, follow_redirects=False)
    token = client.csrf("/login")
    codes = [client.post("/login", data={"csrf": token, "email": "x@y.dz", "password": "wrongwrong"}).status_code
             for _ in range(12)]
    assert codes[:10] == [400] * 10
    assert codes[-1] == 429


# ---------------------------------------------------------------- core loop

def test_core_loop(owner):
    order_id = new_order(owner)
    order = _order(order_id)
    assert order.stage == "new" and order.phone == "0555123456" and order.wilaya_code == 16
    detail = owner.get(f"/orders/{order_id}")
    assert "Amina Benali" in detail.text and "باش نبعتوهالك" in detail.text

    response = owner.post_form(f"/orders/{order_id}/wa", {}, from_page=f"/orders/{order_id}", follow_redirects=False)
    target = urlparse(response.headers["location"])
    assert target.netloc == "wa.me" and target.path == "/213555123456"
    text = parse_qs(target.query)["text"][0]
    assert "Amina" in text and "2 500" in text and "الجزائر (16)" in text
    assert _order(order_id).stage == "pending"

    page = owner.post_form(f"/orders/{order_id}/reply", {"text": "wah akid, f sbah"}, from_page=f"/orders/{order_id}")
    assert page.status_code == 200
    assert "الحالة تبدلت أوتوماتيكياً" in page.text
    order = _order(order_id)
    assert order.stage == "confirmed" and order.preferred_slot == "morning"
    with SessionLocal() as db:
        directions = [m.direction for m in db.scalars(select(Message).where(Message.order_id == order_id).order_by(Message.created_at))]
    assert directions == ["out", "in"]


def test_cancel_reply(owner):
    order_id = new_order(owner)
    owner.post_form(f"/orders/{order_id}/wa", {}, follow_redirects=False)
    owner.post_form(f"/orders/{order_id}/reply", {"text": "la ma nhabch"})
    assert _order(order_id).stage == "cancelled"


def test_unclear_reply_not_applied(owner):
    order_id = new_order(owner)
    owner.post_form(f"/orders/{order_id}/wa", {}, follow_redirects=False)
    page = owner.post_form(f"/orders/{order_id}/reply", {"text": "hmm"})
    assert "راجع وقرّر بيدك" in page.text
    assert _order(order_id).stage == "pending"


def test_empty_reply(owner):
    order_id = new_order(owner)
    response = owner.post_form(f"/orders/{order_id}/reply", {"text": "   "}, follow_redirects=False)
    assert response.status_code == 303
    assert _order(order_id).stage == "new"


def test_long_and_emoji(owner):
    name = "عبد الرحمان بن محمد الأمين بن عبد القادر بوعلام الجزائري الطويل"
    order_id = new_order(owner, customer_name=name, note="🎁 cadeau, emballage ✨")
    page = owner.get(f"/orders/{order_id}")
    assert name in page.text and "🎁 cadeau" in page.text


def test_bad_transition(owner):
    order_id = new_order(owner)
    owner.post_form(f"/orders/{order_id}/stage", {"stage": "delivered"}, follow_redirects=True)
    assert _order(order_id).stage == "new"


def test_new_order_validation(owner):
    response = owner.post_form("/orders/new", {"customer_name": "", "phone": "0555123456"})
    assert response.status_code == 400
    assert "اسم الزبون ناقص" in response.text


# ---------------------------------------------------------------- queue

def test_queue_flow(owner):
    first = new_order(owner, customer_name="First Buyer", phone="0555000001")
    second = new_order(owner, customer_name="Second Buyer", phone="0555000002")
    queue = owner.get("/queue")
    assert "First Buyer" in queue.text
    owner.post_form(f"/orders/{first}/stage", {"stage": "confirmed", "next": "queue"}, from_page="/queue")
    queue = owner.get("/queue")
    assert "Second Buyer" in queue.text and "First Buyer" not in queue.text
    skipped = owner.get(f"/queue?skip={second}")
    assert "Second Buyer" in skipped.text  # nothing else left: the skip list resets
    owner.post_form(f"/orders/{second}/stage", {"stage": "cancelled", "reason": "fake", "next": "queue"}, from_page="/queue")
    assert "كلش مريڨل" in owner.get("/queue").text


def test_postponed_returns(owner):
    order_id = new_order(owner)
    owner.post_form(f"/orders/{order_id}/stage", {"stage": "postponed", "postpone_hours": "4"})
    assert "Amina" not in owner.get("/queue").text
    with SessionLocal() as db:
        db.get(Order, order_id).postponed_until = utcnow() - timedelta(minutes=1)
        db.commit()
    assert "Amina" in owner.get("/queue").text


# ---------------------------------------------------------------- import / export

def test_import_csv(owner):
    sample = owner.get("/import/sample.csv").content
    token = owner.csrf("/import")
    report = owner.post("/import", data={"csrf": token}, files={"file": ("orders.csv", sample, "text/csv")})
    assert report.status_code == 200 and "2 طلبية تزادت" in report.text
    with SessionLocal() as db:
        orders = db.scalars(select(Order).order_by(Order.external_id)).all()
        assert [o.wilaya_code for o in orders] == [16, 19]
        assert orders[1].phone == "0661234567" and orders[1].delivery_type == "stopdesk"
        assert orders[0].total_dzd == 2500
    again = owner.post("/import", data={"csrf": token}, files={"file": ("orders.csv", sample, "text/csv")})
    assert "2 كانو موجودين" in again.text


def test_import_semicolon_cp1256(owner):
    # Arabic Excel on Windows saves CSV as Windows-1256 with ";" separators
    content = "الاسم;الهاتف;الولاية;المبلغ\nكريم;0770112233;وهران;3000\n".encode("cp1256")
    report = owner.post("/import", data={"csrf": owner.csrf("/import")}, files={"file": ("x.csv", content, "text/csv")})
    assert "1 طلبية تزادت" in report.text
    with SessionLocal() as db:
        order = db.scalars(select(Order)).one()
        assert order.customer_name == "كريم" and order.wilaya_code == 31 and order.total_dzd == 3000


def test_import_missing_columns(owner):
    report = owner.post("/import", data={"csrf": owner.csrf("/import")},
                        files={"file": ("x.csv", b"foo,bar\n1,2\n", "text/csv")})
    assert "ما لقيناش عمود الاسم" in report.text


def test_export_and_ship(owner):
    a = new_order(owner, customer_name="Confirmed One", phone="0555000011")
    b = new_order(owner, customer_name="Still New", phone="0555000012")
    owner.post_form(f"/orders/{a}/stage", {"stage": "confirmed"})
    token = owner.csrf("/orders")
    export = owner.post("/orders/bulk", data={"csrf": token, "ids": [a, b], "action": "export", "carrier": "yalidine"})
    assert export.status_code == 200 and export.headers["content-type"].startswith("text/csv")
    body = export.content.decode("utf-8")
    assert body.startswith("﻿reference,nom_client")
    assert "Confirmed One" in body and "Still New" not in body
    owner.post("/orders/bulk", data={"csrf": token, "ids": [a, b], "action": "ship", "carrier": "zr"})
    assert _order(a).stage == "shipped" and _order(a).carrier == "zr"
    assert _order(b).stage == "new"


# ---------------------------------------------------------------- returns / blacklist / risk

def test_return_blacklists(owner):
    first = new_order(owner, phone="0555999888")
    for stage in ("confirmed", "shipped"):
        owner.post_form(f"/orders/{first}/stage", {"stage": stage})
    owner.post_form(f"/orders/{first}/stage", {"stage": "returned", "blacklist": "1"})
    second = new_order(owner, phone="+213 555 99 98 88", customer_name="Same Buyer")
    risky = _order(second)
    codes = {r["code"] for r in risky.risk_reasons}
    assert {"blacklisted", "past_returns"} <= codes and risky.risk_score >= 60
    with SessionLocal() as db:
        entry = db.scalars(select(BlacklistEntry)).one()
    owner.post_form(f"/blacklist/{entry.id}/delete", {}, from_page="/blacklist")
    assert _order(second).risk_score < risky.risk_score


def test_invalid_phone_is_risky(owner):
    order_id = new_order(owner, phone="021 45 67 89")
    order = _order(order_id)
    assert not order.phone_valid
    assert any(r["code"] == "phone_landline" for r in order.risk_reasons)


# ---------------------------------------------------------------- dashboard

def test_dashboard_numbers(owner):
    ids = [new_order(owner, phone=f"05550000{i:02d}") for i in range(4)]
    owner.post_form(f"/orders/{ids[0]}/stage", {"stage": "confirmed"})
    owner.post_form(f"/orders/{ids[1]}/stage", {"stage": "confirmed"})
    owner.post_form(f"/orders/{ids[2]}/stage", {"stage": "cancelled", "reason": "fake"})
    page = owner.get("/dashboard")
    assert "67%" in page.text            # 2 confirmed of 3 decided
    assert "450" in page.text            # 1 cancelled before shipping x 450 DZD


# ---------------------------------------------------------------- API

def test_api_auth(owner):
    assert owner.post("/api/v1/orders", json={}).status_code == 401
    assert owner.post("/api/v1/orders", json={}, headers={"X-Api-Key": "mrg_wrong"}).status_code == 401


def test_api_create(owner):
    key = _store().api_key
    payload = {"external_id": "W-1", "customer_name": "Yacine", "phone": "0661 22 33 44", "wilaya": "Sétif",
               "items": [{"name": "Montre", "qty": 1, "price": 4800}], "delivery_fee": 600}
    response = owner.post("/api/v1/orders", json=payload, headers={"X-Api-Key": key})
    assert response.status_code == 201
    body = response.json()
    assert body["wilaya_code"] == 19 and body["total_dzd"] == 4800 and body["risk_level"] in ("low", "medium", "high")
    assert owner.get("/api/v1/orders/W-1", headers={"X-Api-Key": key}).json()["id"] == body["id"]


def test_api_idempotent(owner):
    key = _store().api_key
    payload = {"external_id": "W-2", "customer_name": "Yacine", "phone": "0661223344", "wilaya": 19, "total": 1000}
    first = owner.post("/api/v1/orders", json=payload, headers={"X-Api-Key": key})
    second = owner.post("/api/v1/orders", json=payload, headers={"X-Api-Key": key})
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_api_validation(owner):
    key = _store().api_key
    assert owner.post("/api/v1/orders", json={"phone": "0555"}, headers={"X-Api-Key": key}).status_code == 422
    assert owner.post("/api/v1/orders", content=b"not json", headers={"X-Api-Key": key}).status_code == 400
    assert owner.post("/api/v1/orders", json=[1, 2], headers={"X-Api-Key": key}).status_code == 400


# ---------------------------------------------------------------- multi-tenancy and roles

def test_multi_tenant(owner):
    order_id = new_order(owner)
    key_a = _store().api_key
    other = make_client()
    signup(other, store="Other Shop", email="other@test.dz")
    assert other.get(f"/orders/{order_id}").status_code == 404
    assert "Amina" not in other.get("/orders").text
    assert "Amina" not in other.get("/queue").text
    response = other.post_form(f"/orders/{order_id}/stage", {"stage": "cancelled"}, follow_redirects=False)
    assert response.status_code == 404
    assert _order(order_id).stage == "new"
    with SessionLocal() as db:
        key_b = db.scalar(select(Store.api_key).where(Store.name == "Other Shop"))
    assert owner.get(f"/api/v1/orders/{order_id}", headers={"X-Api-Key": key_b}).status_code == 404
    assert owner.get(f"/api/v1/orders/{order_id}", headers={"X-Api-Key": key_a}).status_code == 200


def test_agent_forbidden(owner):
    owner.post_form("/team", {"name": "Agent", "email": "agent@test.dz", "password": "password123", "role": "agent"},
                    from_page="/team")
    agent = make_client()
    agent.post("/login", data={"csrf": agent.csrf("/login"), "email": "agent@test.dz", "password": "password123"})
    assert agent.get("/orders").status_code == 200
    assert agent.get("/settings").status_code == 403
    assert agent.get("/team").status_code == 403
    response = agent.post_form("/settings/delete-store", {"confirm": "Boutique Test"}, from_page="/orders")
    assert response.status_code == 403


def test_delete_store(owner):
    new_order(owner)
    response = owner.post_form("/settings/delete-store", {"confirm": "wrong name"}, from_page="/settings",
                               follow_redirects=False)
    assert _store() is not None
    owner.post_form("/settings/delete-store", {"confirm": "Boutique Test"}, from_page="/settings")
    with SessionLocal() as db:
        for model in (Store, User, Order):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    assert response.status_code == 303


def test_secrets_encrypted(owner):
    owner.post_form("/settings", {"store_name": "Boutique Test", "lang": "ar", "whatsapp_mode": "cloud",
                                  "wa_access_token": "EAAG-secret-token", "wa_phone_number_id": "123"},
                    from_page="/settings")
    store = _store()
    assert store.settings["wa_access_token"].startswith("enc:")
    assert "EAAG" not in json.dumps(store.settings)
    from app.store_settings import get_settings
    assert get_settings(store)["wa_access_token"] == "EAAG-secret-token"
    # saving again with an empty secret keeps it
    owner.post_form("/settings", {"store_name": "Boutique Test", "whatsapp_mode": "cloud", "wa_access_token": ""},
                    from_page="/settings")
    assert get_settings(_store())["wa_access_token"] == "EAAG-secret-token"


# ---------------------------------------------------------------- WhatsApp Cloud webhook

def _cloud_store(owner, secret="app-secret"):
    owner.post_form("/settings", {"store_name": "Boutique Test", "whatsapp_mode": "cloud", "wa_phone_number_id": "PNID",
                                  "wa_app_secret": secret, "wa_verify_token": "verify-me", "wa_access_token": "tok"},
                    from_page="/settings")


def _webhook_payload(text="wah", msg_id="wamid.1", sender="213555123456"):
    return {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "PNID"},
                                              "messages": [{"from": sender, "id": msg_id, "type": "text",
                                                            "text": {"body": text}}]}}]}]}


def _signed(body: bytes, secret="app-secret"):
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(),
            "Content-Type": "application/json"}


def test_webhook_verify(owner):
    _cloud_store(owner)
    ok = owner.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    bad = owner.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"})
    assert bad.status_code == 403


def test_webhook_confirms(owner):
    _cloud_store(owner)
    order_id = new_order(owner)
    body = json.dumps(_webhook_payload()).encode()
    response = owner.post("/webhooks/whatsapp", content=body, headers=_signed(body))
    assert response.status_code == 200 and response.json()["handled"] == 1
    assert _order(order_id).stage == "confirmed"


def test_webhook_replay(owner):
    _cloud_store(owner)
    order_id = new_order(owner)
    body = json.dumps(_webhook_payload(text="ghodwa")).encode()
    owner.post("/webhooks/whatsapp", content=body, headers=_signed(body))
    second = owner.post("/webhooks/whatsapp", content=body, headers=_signed(body))
    assert second.json()["handled"] == 0
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Message).where(Message.order_id == order_id)) == 1


def test_webhook_bad_signature(owner):
    _cloud_store(owner)
    order_id = new_order(owner)
    body = json.dumps(_webhook_payload()).encode()
    response = owner.post("/webhooks/whatsapp", content=body, headers=_signed(body, secret="forged"))
    assert response.status_code == 401
    assert _order(order_id).stage == "new"


# ---------------------------------------------------------------- jobs

def test_followup_job(owner):
    order_id = new_order(owner)
    owner.post_form(f"/orders/{order_id}/wa", {}, follow_redirects=False)
    assert run_followups()["no_answer"] == 0  # too early
    with SessionLocal() as db:
        db.get(Order, order_id).last_contact_at = utcnow() - timedelta(hours=3)
        db.commit()
    assert run_followups()["no_answer"] == 1
    assert _order(order_id).stage == "no_answer"


def test_cron_endpoint_needs_token(client):
    assert client.post("/tasks/run").status_code == 403
    assert client.post("/tasks/run", headers={"X-Cron-Token": "cron-test"}).status_code == 200


# ---------------------------------------------------------------- demo

def test_demo_never_opens_whatsapp(client):
    from app.seed import DEMO_EMAIL, DEMO_PASSWORD, ensure_demo

    with SessionLocal() as db:
        ensure_demo(db)
        db.commit()
    client.post("/login", data={"csrf": client.csrf("/login"), "email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    with SessionLocal() as db:
        order_id = db.scalar(select(Order.id).where(Order.stage == "new"))
    response = client.post_form(f"/orders/{order_id}/wa", {}, follow_redirects=False)
    assert "wa.me" not in response.headers["location"]
    locked = client.post_form("/settings", {"store_name": "Hacked"}, from_page="/settings", follow_redirects=False)
    assert locked.status_code == 303
    assert _store().name == "Lina Beauty DZ"


def test_french_interface(owner):
    owner.get("/lang/fr")
    assert "Tableau de bord" in owner.get("/dashboard").text
    assert 'dir="ltr"' in owner.get("/dashboard").text


def test_pages_render_with_data(owner):
    new_order(owner)
    for path in ("/dashboard", "/dashboard?days=7", "/orders", "/orders?stage=new", "/orders?q=0555", "/queue",
                 "/import", "/blacklist", "/settings", "/team", "/orders/new", "/privacy"):
        assert owner.get(path).status_code == 200, path


def test_security_headers(client):
    response = client.get("/")
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_password_hash_not_plain():
    hashed = hash_password("password123")
    assert hashed != "password123" and hashed.startswith("$2")
