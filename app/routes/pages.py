"""Signed-in pages."""

import re
import secrets
from math import ceil
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import backup, whatsapp
from ..carriers import CARRIERS, export_csv
from ..config import settings
from ..db import get_db
from ..i18n import translate
from ..importer import SAMPLE_CSV, import_csv
from ..models import STAGES, BlacklistEntry, Order, Store, User
from ..ratelimit import limiter
from ..security import hash_password
from ..services import (
    AUTO_APPLY,
    TRANSITIONS,
    OrderError,
    add_event,
    add_to_blacklist,
    apply_reading,
    create_order,
    log_outbound,
    next_in_queue,
    queue_size,
    read_buyer_reply,
    set_stage,
)
from ..stats import dashboard as dashboard_stats
from ..store_settings import DEFAULTS, SECRET_KEYS, get_settings, update_settings
from ..web import check_csrf, current_store, current_user, flash, get_lang, owner_only, render, scoped_order

router = APIRouter()
PAGE_SIZE = 40
MAX_UPLOAD = 2 * 1024 * 1024


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _safe_next(value: str | None, default: str) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return default


def _demo_locked(request: Request, store: Store) -> RedirectResponse | None:
    """The shared demo store is read-mostly: visitors can confirm orders but not change settings."""
    if (store.settings or {}).get("demo"):
        flash(request, "demo_locked", "error")
        back = urlparse(request.headers.get("referer") or "").path
        return _redirect(_safe_next(back, "/dashboard"))
    return None


def _shell(db: Session, store: Store, user: User) -> dict:
    from ..models import Contact

    unread = db.scalar(select(func.coalesce(func.sum(Contact.unread), 0)).where(Contact.store_id == store.id)) or 0
    return {"store": store, "user": user, "queue_count": queue_size(db, store.id), "inbox_unread": unread}


# ---------------------------------------------------------------- dashboard

@router.get("/dashboard")
def dashboard(request: Request, days: int = 0, db: Session = Depends(get_db),
              user: User = Depends(current_user), store: Store = Depends(current_store)):
    from ..finance import summary as money_summary
    from .ops import DASHBOARD_PANELS

    prefs = user.prefs or {}
    days = days if days in (7, 30, 90) else int(prefs.get("days") or 30)
    stats = dashboard_stats(db, store, days)
    any_orders = db.scalar(select(func.count()).select_from(Order).where(Order.store_id == store.id)) or 0
    hidden = set(prefs.get("hidden_panels") or [])
    money = money_summary(db, store) if user.role == "owner" and "money" not in hidden else None
    return render(request, "dashboard.html", {**_shell(db, store, user), "s": stats, "any_orders": any_orders,
                                              "nav": "dashboard", "hidden": hidden, "panels": DASHBOARD_PANELS,
                                              "money": money})


# ---------------------------------------------------------------- orders list

def _stage_counts(db: Session, store_id: str) -> dict:
    rows = db.execute(select(Order.stage, func.count()).where(Order.store_id == store_id).group_by(Order.stage)).all()
    counts = dict(rows)
    counts["all"] = sum(counts.values())
    return counts


@router.get("/orders")
def orders(request: Request, stage: str = "", q: str = "", wilaya: str = "", tag: str = "", source: str = "",
           risk: str = "", page: int = 1,
           db: Session = Depends(get_db), user: User = Depends(current_user), store: Store = Depends(current_store)):
    from ..models import SavedView

    query = select(Order).where(Order.store_id == store.id)
    if stage in STAGES:
        query = query.where(Order.stage == stage)
    tag = tag.strip()[:30]
    if tag:
        import json

        from sqlalchemy import String, cast

        query = query.where(cast(Order.tags, String).like("%" + json.dumps(tag) + "%"))
    source = source.strip()[:20]
    if source:
        query = query.where(Order.source == source)
    if risk in ("high", "medium", "low"):
        query = query.where(Order.risk_score >= 60 if risk == "high" else
                            (Order.risk_score >= 30) & (Order.risk_score < 60) if risk == "medium" else
                            Order.risk_score < 30)
    q = q.strip()[:80]
    if q:
        digits = re.sub(r"\D", "", q)
        if digits.startswith("213"):
            digits = digits[3:]
        digits = digits.lstrip("0")
        conditions = [Order.customer_name.ilike(f"%{q}%"), Order.external_id.ilike(f"%{q}%")]
        if len(digits) >= 3:
            conditions.append(Order.phone.contains(digits))
        query = query.where(or_(*conditions))
    wilaya_code = int(wilaya) if wilaya.isdigit() else None
    if wilaya_code:
        query = query.where(Order.wilaya_code == wilaya_code)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    pages = max(1, ceil(total / PAGE_SIZE))
    page = min(max(1, page), pages)
    rows = db.scalars(query.order_by(Order.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    return render(request, "orders/list.html", {
        **_shell(db, store, user), "nav": "orders", "orders": rows, "counts": _stage_counts(db, store.id),
        "stage": stage if stage in STAGES else "", "q": q, "wilaya": wilaya_code, "page": page, "pages": pages,
        "total": total, "carriers": CARRIERS, "tag": tag, "source": source, "risk": risk,
        "views": db.scalars(select(SavedView).where(SavedView.user_id == user.id).order_by(SavedView.created_at)).all(),
        "query_string": request.url.query,
    })


@router.post("/orders/bulk", dependencies=[Depends(check_csrf)])
async def orders_bulk(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
                      store: Store = Depends(current_store)):
    form = await request.form()
    ids = [i for i in form.getlist("ids") if isinstance(i, str)][:500]
    action = form.get("action", "")
    carrier = str(form.get("carrier", "")) if form.get("carrier") in CARRIERS else ""
    selected = db.scalars(select(Order).where(Order.store_id == store.id, Order.id.in_(ids))).all() if ids else []
    if action == "export":
        chosen = [o for o in selected if o.stage in ("confirmed", "shipped")]
        if not chosen:
            flash(request, "nothing_selected", "error")
            return _redirect(_safe_next(form.get("next"), "/orders?stage=confirmed"))
        name = f"mrigel-{carrier or 'export'}-{len(chosen)}.csv"
        return Response(export_csv(chosen), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
    if action == "ship":
        moved = 0
        for order in selected:
            if order.stage == "confirmed":
                order.carrier = carrier or order.carrier
                set_stage(db, order, "shipped", user_id=user.id)
                moved += 1
        db.commit()
        flash(request, "shipped_n" if moved else "nothing_selected", "success" if moved else "error", n=moved)
    return _redirect(_safe_next(form.get("next"), "/orders?stage=confirmed"))


# ---------------------------------------------------------------- new order

@router.get("/orders/new")
def order_new_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
                   store: Store = Depends(current_store)):
    return render(request, "orders/new.html", {**_shell(db, store, user), "nav": "orders", "values": {}})


@router.post("/orders/new", dependencies=[Depends(check_csrf)])
async def order_new(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
                    store: Store = Depends(current_store)):
    form = dict(await request.form())
    data = {k: str(v) for k, v in form.items() if k != "csrf"}
    data["items"] = [{"name": data.get("product", ""), "qty": data.get("qty", "1")}] if data.get("product") else []
    try:
        order = create_order(db, store, data, source="manual", user_id=user.id)
        db.commit()
    except OrderError as exc:
        db.rollback()
        return render(request, "orders/new.html", {**_shell(db, store, user), "nav": "orders", "values": data,
                                                    "error": str(exc)}, status_code=400)
    flash(request, "order_created")
    return _redirect(f"/orders/{order.id}")


# ---------------------------------------------------------------- order detail

def _detail_context(db: Session, store: Store, user: User, order: Order, lang: str) -> dict:
    cfg = get_settings(store)
    preview = whatsapp.confirmation_text(order, store)
    names = {u.id: u.name for u in db.scalars(select(User).where(User.store_id == store.id))}
    return {
        **_shell(db, store, user), "nav": "orders", "order": order, "preview": preview,
        "wa_mode": cfg.get("whatsapp_mode", "assisted"),
        "allowed": TRANSITIONS.get(order.stage, set()),
        "names": names, "carriers": CARRIERS,
        "risk_reasons": [_reason_text(r, lang) for r in order.risk_reasons or []],
        "waiting": [m for m in order.messages if m.direction == "out" and m.status in ("todo", "queued", "failed")
                    and m.kind != "chat"],
    }


def _reason_text(reason: dict, lang: str) -> dict:
    code = reason.get("code", "")
    text = translate(f"reason_{code}", lang, n=reason.get("n", ""), rate=reason.get("rate", ""))
    if code == "wilaya_returns":
        text += " " + translate("reason_wilaya_own" if reason.get("own") else "reason_wilaya_baseline", lang)
    return {"text": text, "points": reason.get("points", 0)}


@router.get("/orders/{order_id}")
def order_detail(order_id: str, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(current_user), store: Store = Depends(current_store)):
    order = scoped_order(db, store, order_id)
    return render(request, "orders/detail.html", _detail_context(db, store, user, order, get_lang(request)))


@router.post("/orders/{order_id}/stage", dependencies=[Depends(check_csrf)])
def order_stage(order_id: str, request: Request, stage: str = Form(...), reason: str = Form(""),
                blacklist: str = Form(""), postpone_hours: int = Form(24), next: str = Form(""),
                db: Session = Depends(get_db), user: User = Depends(current_user), store: Store = Depends(current_store)):
    order = scoped_order(db, store, order_id)
    try:
        set_stage(db, order, stage, user_id=user.id, reason=reason, blacklist=bool(blacklist),
                  postpone_hours=max(1, min(postpone_hours, 24 * 14)))
        db.commit()
    except OrderError as exc:
        db.rollback()
        flash(request, str(exc), "error")
    if next == "queue":
        skips = [s for s in request.session.get("queue_skip", []) if s != order_id]
        request.session["queue_skip"] = skips
        return _redirect("/queue")
    return _redirect(f"/orders/{order.id}")


@router.post("/orders/{order_id}/wa", dependencies=[Depends(check_csrf)])
def order_whatsapp(order_id: str, request: Request, text: str = Form(""), next: str = Form(""),
                   db: Session = Depends(get_db), user: User = Depends(current_user),
                   store: Store = Depends(current_store)):
    """Assisted mode: log the message and open WhatsApp with it. Cloud mode: send through the API."""
    order = scoped_order(db, store, order_id)
    body = (text.strip() or whatsapp.confirmation_text(order, store))[:4000]
    cfg = get_settings(store)
    if cfg.get("whatsapp_mode") == "cloud" and not (store.settings or {}).get("demo"):
        try:
            is_first = not any(m.direction == "out" for m in order.messages)
            if is_first and cfg.get("wa_template_name"):
                provider_id = whatsapp.cloud_send_template(
                    store, order.phone, [order.customer_name.split(" ")[0], order.items_label or "—", str(order.total_dzd)])
            else:
                provider_id = whatsapp.cloud_send_text(store, order.phone, body)
            log_outbound(db, order, body, user_id=user.id, provider_id=provider_id or None, status="sent")
            db.commit()
        except whatsapp.CloudError as exc:
            db.rollback()
            key = "err_cloud_not_configured" if str(exc) == "not_configured" else "err_cloud_send"
            flash(request, key, "error", e=str(exc))
        return _redirect("/queue" if next == "queue" else f"/orders/{order.id}")
    log_outbound(db, order, body, user_id=user.id, status="opened")
    db.commit()
    if (store.settings or {}).get("demo"):
        # demo numbers have a real format: never open a chat with whoever owns them
        flash(request, "demo_not_sent", "success")
        return _redirect("/queue" if next == "queue" else f"/orders/{order.id}")
    return _redirect(whatsapp.wa_link(order.phone, body))


@router.post("/orders/{order_id}/reply", dependencies=[Depends(check_csrf)])
def order_reply(order_id: str, request: Request, text: str = Form(""), next: str = Form(""),
                db: Session = Depends(get_db), user: User = Depends(current_user), store: Store = Depends(current_store)):
    order = scoped_order(db, store, order_id)
    text = text.strip()[:2000]
    if not text:
        return _redirect("/queue" if next == "queue" else f"/orders/{order.id}")
    reading = read_buyer_reply(db, store, order, text, user_id=user.id)
    applied = apply_reading(db, order, reading, user_id=user.id)
    db.commit()
    lang = get_lang(request)
    context = _detail_context(db, store, user, order, lang)
    context.update({"reading": reading, "applied": applied, "suggested_stage": AUTO_APPLY.get(reading.intent),
                    "reply_text": text})
    if next == "queue":
        context.update({"queue_left": queue_size(db, store.id)})
        return render(request, "queue.html", context)
    return render(request, "orders/detail.html", context)


@router.post("/orders/{order_id}/note", dependencies=[Depends(check_csrf)])
def order_note(order_id: str, request: Request, text: str = Form(""), db: Session = Depends(get_db),
               user: User = Depends(current_user), store: Store = Depends(current_store)):
    order = scoped_order(db, store, order_id)
    if text.strip():
        add_event(db, order, "note", text.strip()[:1000], user_id=user.id)
        db.commit()
    return _redirect(f"/orders/{order.id}#timeline")


@router.post("/orders/{order_id}/shipping", dependencies=[Depends(check_csrf)])
def order_shipping(order_id: str, request: Request, carrier: str = Form(""), tracking: str = Form(""),
                   db: Session = Depends(get_db), user: User = Depends(current_user), store: Store = Depends(current_store)):
    order = scoped_order(db, store, order_id)
    order.carrier = carrier if carrier in CARRIERS else ""
    order.tracking = tracking.strip()[:60]
    db.commit()
    flash(request, "saved_ok")
    return _redirect(f"/orders/{order.id}")


# ---------------------------------------------------------------- queue

@router.get("/queue")
def queue(request: Request, skip: str = "", db: Session = Depends(get_db), user: User = Depends(current_user),
          store: Store = Depends(current_store)):
    skips = list(request.session.get("queue_skip", []))
    if skip:
        skips.append(skip)
        request.session["queue_skip"] = skips[-200:]
    order = next_in_queue(db, store.id, skip=skips)
    if order is None and skips:
        request.session["queue_skip"] = []
        order = next_in_queue(db, store.id)
    context = {**_shell(db, store, user), "nav": "queue", "queue_left": queue_size(db, store.id)}
    if order:
        context.update(_detail_context(db, store, user, order, get_lang(request)))
        context["nav"] = "queue"
    return render(request, "queue.html", context)


# ---------------------------------------------------------------- import + API

@router.get("/import")
def import_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
                store: Store = Depends(current_store)):
    return render(request, "import.html", {**_shell(db, store, user), "nav": "import"})


@router.get("/import/sample.csv")
def import_sample(user: User = Depends(current_user)):
    return Response(("﻿" + SAMPLE_CSV).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="mrigel-exemple.csv"'})


@router.post("/import", dependencies=[Depends(check_csrf)])
async def import_upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                        user: User = Depends(current_user), store: Store = Depends(current_store)):
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        return render(request, "import.html", {**_shell(db, store, user), "nav": "import",
                                               "upload_error": "err_file_big"}, status_code=400)
    report = import_csv(db, store, data, user_id=user.id)
    db.commit()
    return render(request, "import.html", {**_shell(db, store, user), "nav": "import", "report": report})


# ---------------------------------------------------------------- blacklist

@router.get("/blacklist")
def blacklist(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
              store: Store = Depends(current_store)):
    entries = db.scalars(select(BlacklistEntry).where(BlacklistEntry.store_id == store.id)
                         .order_by(BlacklistEntry.created_at.desc())).all()
    return render(request, "blacklist.html", {**_shell(db, store, user), "nav": "blacklist", "entries": entries})


@router.post("/blacklist", dependencies=[Depends(check_csrf)])
def blacklist_add(request: Request, phone: str = Form(""), reason: str = Form(""), db: Session = Depends(get_db),
                  user: User = Depends(current_user), store: Store = Depends(current_store)):
    if phone.strip():
        add_to_blacklist(db, store.id, phone, reason.strip(), user.id)
        db.commit()
        flash(request, "saved_ok")
    return _redirect("/blacklist")


@router.post("/blacklist/{entry_id}/delete", dependencies=[Depends(check_csrf)])
def blacklist_remove(entry_id: str, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(current_user), store: Store = Depends(current_store)):
    entry = db.scalar(select(BlacklistEntry).where(BlacklistEntry.id == entry_id, BlacklistEntry.store_id == store.id))
    if entry:
        phone = entry.phone
        db.delete(entry)
        db.flush()
        from ..risk import apply_risk

        for order in db.scalars(select(Order).where(Order.store_id == store.id, Order.phone == phone,
                                                    Order.stage.in_(("new", "pending", "postponed", "no_answer", "confirmed")))):
            apply_risk(db, order)
        db.commit()
    return _redirect("/blacklist")


# ---------------------------------------------------------------- settings (owner)

@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db), user: User = Depends(owner_only),
                  store: Store = Depends(current_store)):
    cfg = get_settings(store)
    return render(request, "settings.html", {**_shell(db, store, user), "nav": "settings", "cfg": cfg,
                                             "store_empty": backup.store_is_empty(db, store),
                                             "secrets_set": {k: bool(cfg.get(k)) for k in SECRET_KEYS},
                                             "webhook_url": str(request.base_url).rstrip("/") + "/webhooks/whatsapp",
                                             "server_ai": bool(settings.gemini_api_key)})


@router.post("/settings", dependencies=[Depends(check_csrf)])
async def settings_save(request: Request, db: Session = Depends(get_db), user: User = Depends(owner_only),
                        store: Store = Depends(current_store)):
    if (locked := _demo_locked(request, store)):
        return locked
    form = await request.form()
    name = str(form.get("store_name", "")).strip()
    if name:
        store.name = name[:120]
    changes: dict = {}
    for key, default in DEFAULTS.items():
        if isinstance(default, bool):
            if f"bool:{key}" in form:  # the page that shows this checkbox says so
                changes[key] = form.get(key) == "on"
        elif key in form:
            raw = str(form.get(key, ""))
            if isinstance(default, int):
                try:
                    changes[key] = max(0, int(raw or 0))
                except ValueError:
                    continue
            else:
                changes[key] = raw.strip() if key != "confirm_template" else raw.replace("\r\n", "\n").strip()
    if changes.get("whatsapp_mode") not in ("assisted", "cloud"):
        changes.pop("whatsapp_mode", None)
    if changes.get("lang") not in ("ar", "fr"):
        changes.pop("lang", None)
    if "followup_minutes" in changes:
        changes["followup_minutes"] = max(15, int(changes["followup_minutes"] or 120))
    if "max_attempts" in changes:
        changes["max_attempts"] = max(1, min(6, int(changes["max_attempts"] or 3)))
    if "cart_recovery_minutes" in changes:
        changes["cart_recovery_minutes"] = max(10, min(24 * 60, int(changes["cart_recovery_minutes"] or 45)))
    update_settings(store, changes)
    cleared = [k for k in SECRET_KEYS if form.get(f"clear:{k}") == "on"]
    if cleared:  # "disconnect": an empty secret field keeps the old value, so clearing is explicit
        store.settings = {k: v for k, v in (store.settings or {}).items() if k not in cleared}
    db.commit()
    if changes.get("lang"):
        request.session["lang"] = changes["lang"]
    flash(request, "saved_ok")
    return _redirect(_safe_next(str(form.get("next", "")), "/settings"))


@router.post("/settings/api-key", dependencies=[Depends(check_csrf)])
def regenerate_key(request: Request, db: Session = Depends(get_db), user: User = Depends(owner_only),
                   store: Store = Depends(current_store)):
    if (locked := _demo_locked(request, store)):
        return locked
    store.api_key = "mrg_" + secrets.token_urlsafe(24)
    db.commit()
    flash(request, "key_regenerated")
    return _redirect("/import#api")


@router.get("/settings/backup")
def backup_download(db: Session = Depends(get_db), user: User = Depends(owner_only),
                    store: Store = Depends(current_store)):
    from datetime import date

    name = f"mrigel-backup-{date.today().isoformat()}.zip"
    return Response(backup.export_zip(db, store), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.post("/settings/restore", dependencies=[Depends(limiter("restore", 5, 3600)), Depends(check_csrf)])
async def backup_restore(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                         user: User = Depends(owner_only), store: Store = Depends(current_store)):
    if (locked := _demo_locked(request, store)):
        return locked
    try:
        data = backup.read_backup(await file.read(backup.MAX_BYTES + 1))
        counts = backup.restore(db, store, data)
        db.commit()
    except backup.BackupError as exc:
        db.rollback()
        flash(request, f"restore_err_{exc}", "error")
        return _redirect("/settings#backup")
    flash(request, "restore_ok", n=counts.get("orders", 0))
    return _redirect("/dashboard")


@router.post("/settings/delete-store", dependencies=[Depends(check_csrf)])
def delete_store(request: Request, confirm: str = Form(""), db: Session = Depends(get_db),
                 user: User = Depends(owner_only), store: Store = Depends(current_store)):
    """Deletes the store and everything in it (orders, messages, buyers' phones, team)."""
    if (locked := _demo_locked(request, store)):
        return locked
    if confirm.strip() != store.name.strip():
        flash(request, "delete_confirm_wrong", "error")
        return _redirect("/settings#danger")
    db.delete(store)
    db.commit()
    lang = request.session.get("lang")
    request.session.clear()
    if lang:
        request.session["lang"] = lang
    return _redirect("/?deleted=1")


# ---------------------------------------------------------------- team (owner)

@router.get("/team")
def team(request: Request, db: Session = Depends(get_db), user: User = Depends(owner_only),
         store: Store = Depends(current_store)):
    members = db.scalars(select(User).where(User.store_id == store.id).order_by(User.created_at)).all()
    return render(request, "team.html", {**_shell(db, store, user), "nav": "team", "members": members, "values": {}})


@router.post("/team", dependencies=[Depends(limiter("team", 20, 3600)), Depends(check_csrf)])
def team_add(request: Request, name: str = Form(""), email: str = Form(""), password: str = Form(""),
             role: str = Form("agent"), db: Session = Depends(get_db), user: User = Depends(owner_only),
             store: Store = Depends(current_store)):
    if (locked := _demo_locked(request, store)):
        return locked
    from .public import EMAIL

    email = email.strip().lower()
    members = db.scalars(select(User).where(User.store_id == store.id).order_by(User.created_at)).all()
    error = None
    if not name.strip() or not EMAIL.match(email):
        error = "err_fields"
    elif len(password) < 8:
        error = "err_password_short"
    elif db.scalar(select(User.id).where(func.lower(User.email) == email)):
        error = "err_email_taken"
    if error:
        return render(request, "team.html", {**_shell(db, store, user), "nav": "team", "members": members,
                                             "error": error, "values": {"name": name, "email": email}}, status_code=400)
    db.add(User(store_id=store.id, name=name.strip()[:120], email=email, role="owner" if role == "owner" else "agent",
                password_hash=hash_password(password)))
    db.commit()
    flash(request, "member_added")
    return _redirect("/team")


@router.post("/team/{member_id}/password", dependencies=[Depends(limiter("team_pw", 20, 3600)), Depends(check_csrf)])
def team_password(member_id: str, request: Request, password: str = Form(""), db: Session = Depends(get_db),
                  user: User = Depends(owner_only), store: Store = Depends(current_store)):
    """The owner sets a new password for someone on the team (there is no e-mail reset)."""
    if (locked := _demo_locked(request, store)):
        return locked
    member = db.scalar(select(User).where(User.id == member_id, User.store_id == store.id))
    if not member:
        raise HTTPException(status_code=404)
    if len(password) < 8:
        flash(request, "err_password_short", "error")
        return _redirect("/team")
    member.password_hash = hash_password(password)
    db.commit()
    flash(request, "password_changed")
    return _redirect("/team")


@router.post("/team/{member_id}/toggle", dependencies=[Depends(check_csrf)])
def team_toggle(member_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(owner_only),
                store: Store = Depends(current_store)):
    if (locked := _demo_locked(request, store)):
        return locked
    member = db.scalar(select(User).where(User.id == member_id, User.store_id == store.id))
    if not member:
        raise HTTPException(status_code=404)
    if member.id != user.id:
        member.active = not member.active
        db.commit()
    return _redirect("/team")
