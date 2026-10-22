"""Landing, sign up, sign in, language, demo, health."""

import re
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..i18n import LANGS
from ..models import Store, User
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

    ensure_demo(db)
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    lang = request.session.get("lang")
    request.session.clear()
    request.session["user_id"] = user.id
    if lang:
        request.session["lang"] = lang
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/privacy")
def privacy(request: Request):
    return render(request, "privacy.html")


@router.get("/health")
def health():
    return JSONResponse({"ok": True})
