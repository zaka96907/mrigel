"""Launch features: automatic first answer, backup and restore, erase a buyer, disconnect, team
passwords, operator password reset, legal and help pages, demo refresh."""

import io
import json
import zipfile
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app import backup, whatsapp
from app.db import SessionLocal
from app.models import Cart, Contact, Message, Order, OrderEvent, Product, Store, User
from app.store_settings import get_settings

from .conftest import make_client, new_order, signup
from .test_v2 import _cloud, _get, _product, _set, _sig, _stage, _wa_payload


@pytest.fixture
def graph_calls(monkeypatch):
    sent = []
    import httpx

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"message_id": f"m.{len(sent)}"}

    monkeypatch.setattr(httpx, "post", lambda url, json=None, headers=None, timeout=None:
                        sent.append((url, json)) or FakeResponse())
    return sent


def _ig(text="prix?", mid="mid.1", sender="IGSID9"):
    payload = {"object": "instagram", "entry": [{"id": "IG1", "messaging": [
        {"sender": {"id": sender}, "recipient": {"id": "IG1"}, "message": {"mid": mid, "text": text}}]}]}
    return json.dumps(payload).encode()


# ================================================================ automatic first answer

def test_instagram_auto_reply_sends_the_form_link_once(owner, graph_calls):
    _cloud(owner)
    product_id = _product(owner)
    owner.post_form("/settings", {"next": "/integrations", "fb_page_id": "PAGE1", "fb_page_token": "tok",
                                  "ig_account_id": "IG1", "bool:dm_auto_reply": "1", "dm_auto_reply": "on",
                                  "dm_reply_product": product_id}, from_page="/integrations")
    assert owner.post("/webhooks/meta", content=_ig(), headers=_sig(_ig())).json()["handled"] == 1
    url, payload = graph_calls[-1]
    assert url.endswith("/PAGE1/messages") and payload["recipient"]["id"] == "IGSID9"
    assert f"/f/{product_id}" in payload["message"]["text"]
    # a second message the same day gets no second automatic answer
    body = _ig("w livraison?", mid="mid.2")
    owner.post("/webhooks/meta", content=body, headers=_sig(body))
    assert len(graph_calls) == 1
    with SessionLocal() as db:
        kinds = [m.kind for m in db.scalars(select(Message).order_by(Message.created_at))]
        assert kinds.count("auto") == 1 and kinds.count("chat") == 2


def test_auto_reply_is_off_by_default_and_respects_stop(owner, graph_calls):
    _cloud(owner)
    _product(owner)
    owner.post_form("/settings", {"next": "/integrations", "fb_page_id": "PAGE1", "fb_page_token": "tok",
                                  "ig_account_id": "IG1"}, from_page="/integrations")
    owner.post("/webhooks/meta", content=_ig(), headers=_sig(_ig()))
    assert graph_calls == []
    _set(dm_auto_reply=True)
    body = _ig("STOP", mid="mid.9", sender="IGSID10")
    owner.post("/webhooks/meta", content=body, headers=_sig(body))
    assert graph_calls == []


def test_whatsapp_auto_reply_only_for_new_buyers_in_cloud_mode(owner, monkeypatch):
    calls = []
    monkeypatch.setattr(whatsapp, "_cloud_post", lambda cfg, payload: calls.append(payload) or "wamid.x")
    _cloud(owner)
    _product(owner)
    _set(dm_auto_reply=True)
    body = json.dumps(_wa_payload("salam ch7al prix?")).encode()
    owner.post("/webhooks/whatsapp", content=body, headers=_sig(body))
    assert len(calls) == 1 and "/f/" in json.dumps(calls[0], ensure_ascii=False)


def test_demo_store_never_auto_replies(owner, graph_calls):
    _cloud(owner)
    _product(owner)
    owner.post_form("/settings", {"next": "/integrations", "fb_page_id": "PAGE1", "fb_page_token": "tok",
                                  "ig_account_id": "IG1"}, from_page="/integrations")
    with SessionLocal() as db:
        store = db.scalars(select(Store)).first()
        store.settings = {**store.settings, "dm_auto_reply": True, "demo": True}
        db.commit()
    owner.post("/webhooks/meta", content=_ig(), headers=_sig(_ig()))
    assert graph_calls == []


# ================================================================ backup and restore

def test_backup_then_restore_into_a_new_store(owner):
    face = _product(owner, name="Crème visage", sku="CR-01")
    oil = _product(owner, name="Huile argan", sku="HU-01")
    owner.post_form(f"/products/{face}", {"name": "Crème visage", "sku": "CR-01", "price_dzd": "2500",
                                          "upsell_product_id": oil, "upsell_price_dzd": "900", "form_enabled": "on"},
                    from_page=f"/products/{face}")
    first = new_order(owner, product="Crème visage")
    for stage in ("confirmed", "shipped", "delivered"):
        _stage(owner, first, stage)
    new_order(owner, phone="0661223344")
    _set(confirm_template="Salam {name}", wa_access_token="secret-token")
    response = owner.get("/settings/backup")
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert {"backup.json", "orders.csv", "products.csv", "contacts.csv"} <= set(archive.namelist())
    data = json.loads(archive.read("backup.json"))
    assert "wa_access_token" not in data["settings"]  # secrets stay on the server
    assert "Crème visage" in archive.read("products.csv").decode("utf-8-sig")

    with make_client() as other:
        signup(other, store="Nouvelle", email="new@test.dz")
        restored = other.post("/settings/restore", data={"csrf": other.csrf("/settings")},
                              files={"file": ("b.zip", response.content, "application/zip")}, follow_redirects=False)
        assert restored.status_code == 303 and restored.headers["location"] == "/dashboard"
        with SessionLocal() as db:
            new_store = db.scalar(select(Store).where(Store.name == "Nouvelle"))
            orders = db.scalars(select(Order).where(Order.store_id == new_store.id)).all()
            assert len(orders) == 2 and {o.id for o in orders}.isdisjoint({first})
            delivered = next(o for o in orders if o.stage == "delivered")
            assert db.scalar(select(func.count()).select_from(OrderEvent).where(OrderEvent.order_id == delivered.id)) >= 3
            products = {p.name: p for p in db.scalars(select(Product).where(Product.store_id == new_store.id))}
            assert products["Crème visage"].upsell_product_id == products["Huile argan"].id
            assert get_settings(new_store)["confirm_template"] == "Salam {name}"
            assert get_settings(new_store)["wa_access_token"] == ""
            # the first store is untouched
            assert db.scalar(select(func.count()).select_from(Order).where(Order.store_id != new_store.id)) == 2
        # a store with data refuses a restore
        again = other.post("/settings/restore", data={"csrf": other.csrf("/settings")},
                           files={"file": ("b.zip", response.content, "application/zip")})
        assert "فارغ" in again.text or "vide" in again.text


def test_restore_rejects_other_files(owner):
    bad = owner.post("/settings/restore", data={"csrf": owner.csrf("/settings")},
                     files={"file": ("x.zip", b"not a zip", "application/zip")})
    assert bad.status_code == 200 and ("مريڨل" in bad.text or "Mrigel" in bad.text)
    with pytest.raises(backup.BackupError):
        backup.read_backup(b"PK\x03\x04garbage")


# ================================================================ erase a buyer, disconnect

def test_forget_a_buyer_deletes_conversation_orders_and_carts(owner, monkeypatch):
    monkeypatch.setattr(whatsapp, "_cloud_post", lambda cfg, payload: "wamid.x")
    _cloud(owner)
    order_id = new_order(owner, phone="0661000111")
    for stage in ("confirmed", "shipped", "delivered"):
        _stage(owner, order_id, stage)
    keep = new_order(owner, phone="0555999888")
    body = json.dumps(_wa_payload("merci")).encode()
    owner.post("/webhooks/whatsapp", content=body, headers=_sig(body))
    with SessionLocal() as db:
        store = db.scalars(select(Store)).first()
        db.add(Cart(store_id=store.id, phone="0661000111", customer_name="Lamia"))
        db.commit()
        contact_id = db.scalar(select(Contact.id).where(Contact.handle == "0661000111"))
    response = owner.post_form(f"/inbox/{contact_id}/forget", {}, from_page="/inbox", follow_redirects=False)
    assert response.status_code == 303
    with SessionLocal() as db:
        assert db.get(Contact, contact_id) is None and db.get(Order, order_id) is None
        assert db.scalar(select(func.count()).select_from(Cart)) == 0
        assert db.scalar(select(func.count()).select_from(Message).where(Message.contact_id == contact_id)) == 0
        assert db.get(Order, keep) is not None


def test_disconnect_clears_a_saved_secret(owner):
    owner.post_form("/settings", {"next": "/integrations", "fb_page_token": "tok", "shopify_secret": "shh"},
                    from_page="/integrations")
    store = _get(Store, owner_store_id())
    assert get_settings(store)["fb_page_token"] == "tok"
    owner.post_form("/settings", {"next": "/integrations", "clear:fb_page_token": "on"}, from_page="/integrations")
    store = _get(Store, owner_store_id())
    assert get_settings(store)["fb_page_token"] == "" and get_settings(store)["shopify_secret"] == "shh"


def owner_store_id() -> str:
    with SessionLocal() as db:
        return db.scalars(select(Store.id)).first()


# ================================================================ passwords

def test_owner_sets_a_new_password_for_an_agent(owner):
    owner.post_form("/team", {"name": "Sara", "email": "agent@test.dz", "password": "password123"}, from_page="/team")
    with SessionLocal() as db:
        agent_id = db.scalar(select(User.id).where(User.email == "agent@test.dz"))
    assert owner.post_form(f"/team/{agent_id}/password", {"password": "short"}, from_page="/team",
                           follow_redirects=False).status_code == 303
    owner.post_form(f"/team/{agent_id}/password", {"password": "nouveau-pass"}, from_page="/team")
    with make_client() as agent:
        ok = agent.post("/login", data={"csrf": agent.csrf("/login"), "email": "agent@test.dz",
                                        "password": "nouveau-pass"}, follow_redirects=False)
        assert ok.status_code == 303


def test_admin_reset_is_off_without_a_token_and_checks_it(client, monkeypatch):
    from app import config

    assert client.get("/admin/reset").status_code == 404
    signup(client)
    object.__setattr__(config.settings, "admin_token", "operator-token")
    try:
        with make_client() as op:
            wrong = op.post("/admin/reset", data={"csrf": op.csrf("/login"), "token": "nope",
                                                  "email": "owner@test.dz", "password": "brand-new-1"})
            assert wrong.status_code == 400
            done = op.post("/admin/reset", data={"csrf": op.csrf("/login"), "token": "operator-token",
                                                 "email": "owner@test.dz", "password": "brand-new-1"})
            assert done.status_code == 200 and "owner@test.dz" in done.text
            login = op.post("/login", data={"csrf": op.csrf("/login"), "email": "owner@test.dz",
                                            "password": "brand-new-1"}, follow_redirects=False)
            assert login.status_code == 303
    finally:
        object.__setattr__(config.settings, "admin_token", "")


# ================================================================ public pages

@pytest.mark.parametrize("path", ["/privacy", "/terms", "/data-deletion", "/help", "/forgot"])
def test_public_pages_in_both_languages(client, path):
    for lang in ("ar", "fr"):
        client.get(f"/lang/{lang}")
        page = client.get(path)
        assert page.status_code == 200 and "{{" not in page.text


def test_help_page_shows_this_sites_webhook_addresses(client):
    page = client.get("/help")
    assert "http://testserver/webhooks/whatsapp" in page.text and "http://testserver/data-deletion" in page.text


# ================================================================ demo refresh

def test_demo_is_rebuilt_after_a_day(monkeypatch):
    from app import config
    from app.seed import DEMO_EMAIL

    object.__setattr__(config.settings, "demo_mode", True)
    try:
        with make_client() as visitor:
            assert visitor.get("/demo", follow_redirects=False).status_code == 303
            with SessionLocal() as db:
                user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
                store = db.get(Store, user.store_id)
                old_id = store.id
                store.created_at = store.created_at - timedelta(days=2)
                db.commit()
            assert visitor.get("/demo", follow_redirects=False).status_code == 303
            with SessionLocal() as db:
                user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
                assert user.store_id != old_id and db.get(Store, old_id) is None
                assert db.scalar(select(func.count()).select_from(Order).where(Order.store_id == user.store_id)) >= 100
            assert visitor.get("/dashboard").status_code == 200
    finally:
        object.__setattr__(config.settings, "demo_mode", False)
