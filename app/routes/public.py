"""Landing, sign up, sign in, language, demo, health."""

import hmac
import re
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..i18n import LANGS
from ..models import Store, User, utcnow
from ..ratelimit import limiter
from ..security import hash_password, verify_password
from ..web import check_csrf, render

router = APIRouter()
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.get("/")
def landing(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "landing.html")


@router.get("/lang/{code}")
def set_lang(code: str, request: Request):
    if code in LANGS:
        request.session["lang"] = code
    # go back to the same page, but never to another site: keep only path and query
    referer = urlparse(request.headers.get("referer") or "/")
    back = referer.path if referer.path.startswith("/") and not referer.path.startswith("//") else "/"
    if referer.query:
        back += "?" + referer.query
    return RedirectResponse(back, status_code=303)


@router.get("/signup")
def signup_page(request: Request):
    return render(request, "auth/signup.html", {"values": {}})


@router.post("/signup", dependencies=[Depends(limiter("signup", 5, 3600)), Depends(check_csrf)])
def signup(request: Request, store_name: str = Form(""), name: str = Form(""), email: str = Form(""),
           password: str = Form(""), db: Session = Depends(get_db)):
    values = {"store_name": store_name.strip(), "name": name.strip(), "email": email.strip().lower()}
    error = None
    if not all(values.values()) or not EMAIL.match(values["email"]):
        error = "err_fields"
    elif len(password) < 8:
        error = "err_password_short"
    elif db.scalar(select(User.id).where(func.lower(User.email) == values["email"])):
        error = "err_email_taken"
    if error:
        return render(request, "auth/signup.html", {"values": values, "error": error}, status_code=400)
    store = Store(name=values["store_name"][:120], settings={"lang": request.session.get("lang", settings.default_lang)})
    db.add(store)
    db.flush()
    user = User(store_id=store.id, name=values["name"][:120], email=values["email"], role="owner",
                password_hash=hash_password(password))
    db.add(user)
    db.commit()
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["lang"] = store.settings.get("lang", "ar")
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/login")
def login_page(request: Request):
    return render(request, "auth/login.html", {"values": {}})


@router.post("/login", dependencies=[Depends(limiter("login", 10, 300)), Depends(check_csrf)])
def login(request: Request, email: str = Form(""), password: str = Form(""), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if not user or not user.active or not verify_password(password, user.password_hash):
        return render(request, "auth/login.html", {"values": {"email": email}, "error": "err_login"}, status_code=400)
    lang = request.session.get("lang")
    request.session.clear()  # new session id content on login
    request.session["user_id"] = user.id
    if lang:
        request.session["lang"] = lang
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/logout", dependencies=[Depends(check_csrf)])
def logout(request: Request):
    lang = request.session.get("lang")
    request.session.clear()
    if lang:
        request.session["lang"] = lang
    return RedirectResponse("/", status_code=303)


@router.get("/demo")
def demo(request: Request, db: Session = Depends(get_db)):
    if not settings.demo_mode:
        return RedirectResponse("/signup", status_code=303)
    from ..seed import DEMO_EMAIL, ensure_demo

    refresh_demo(db)
    try:
        ensure_demo(db)
        db.commit()
    except IntegrityError:  # two visitors created it at the same moment
        db.rollback()
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    lang = request.session.get("lang")
    request.session.clear()
    request.session["user_id"] = user.id
    if lang:
        request.session["lang"] = lang
    return RedirectResponse("/dashboard", status_code=303)


def refresh_demo(db) -> None:
    """The demo is shared by every visitor: rebuild it once a day so it stays clean and its dates stay
    recent (orders "today", payouts this week)."""
    from ..models import Store
    from ..seed import DEMO_EMAIL
    from ..services import as_utc

    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is None:
        return
    store = db.get(Store, user.store_id)
    if store is not None and as_utc(store.created_at) < utcnow() - timedelta(hours=24):
        db.delete(store)  # team, orders, messages... go with it (ON DELETE CASCADE)
        db.commit()
        db.expunge_all()


def _support() -> dict:
    return {"support_email": settings.support_email, "support_whatsapp": settings.support_whatsapp}


@router.get("/privacy")
def privacy(request: Request):
    return render(request, "privacy.html", _support())


@router.get("/terms")
def terms(request: Request):
    return render(request, "terms.html", _support())


@router.get("/data-deletion")
def data_deletion(request: Request):
    return render(request, "data_deletion.html", _support())


@router.get("/help")
def help_page(request: Request):
    return render(request, "help.html", {**_support(), "base": settings.public_url or str(request.base_url).rstrip("/")})


@router.get("/forgot")
def forgot(request: Request):
    return render(request, "auth/forgot.html", _support())


@router.get("/admin/reset")
def admin_reset_page(request: Request):
    if not settings.admin_token:
        raise HTTPException(status_code=404)
    return render(request, "auth/admin_reset.html", {"values": {}})


@router.post("/admin/reset", dependencies=[Depends(limiter("admin_reset", 5, 3600)), Depends(check_csrf)])
def admin_reset(request: Request, token: str = Form(""), email: str = Form(""), password: str = Form(""),
                db: Session = Depends(get_db)):
    """For the operator of this server: set a new password for a merchant who lost theirs. Needs the
    ADMIN_TOKEN environment variable (Render > Environment)."""
    if not settings.admin_token:
        raise HTTPException(status_code=404)
    values = {"email": email.strip().lower()}
    error = None
    if not hmac.compare_digest(settings.admin_token.encode(), token.strip().encode()):
        error = "err_admin_token"
    elif len(password) < 8:
        error = "err_password_short"
    else:
        user = db.scalar(select(User).where(func.lower(User.email) == values["email"]))
        if user is None:
            error = "err_no_such_user"
    if error:
        return render(request, "auth/admin_reset.html", {"values": values, "error": error}, status_code=400)
    user.password_hash = hash_password(password)
    user.active = True
    db.commit()
    return render(request, "auth/admin_reset.html", {"values": {}, "done": values["email"]})


@router.get("/health")
def health():
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------- installable app (PWA)

_STATIC = Path(__file__).resolve().parent.parent / "static"


@router.get("/sw.js")
def service_worker():
    return Response((_STATIC / "sw.js").read_bytes(), media_type="application/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@router.get("/manifest.webmanifest")
def manifest():
    return Response((_STATIC / "manifest.webmanifest").read_bytes(), media_type="application/manifest+json")


@router.get("/offline")
def offline(request: Request):
    return render(request, "offline.html", {})
