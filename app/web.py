"""Shared helpers for the HTML pages: templates, context, auth guards, flash messages."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import __version__
from .algeria import WILAYAS, wilaya_label
from .config import settings
from .db import get_db
from .i18n import LANGS, translate
from .icons import icon
from .models import STAGES, Store, User
from .risk import level as risk_level
from .security import csrf_ok, csrf_token
from .services import as_utc

ALGIERS = ZoneInfo("Africa/Algiers")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def fmt_dzd(value) -> str:
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def fmt_time(value: datetime | None, with_date: bool = True) -> str:
    if not value:
        return "—"
    local = as_utc(value).astimezone(ALGIERS)
    return local.strftime("%d/%m %H:%M" if with_date else "%H:%M")


def ago(value: datetime | None, lang: str = "ar") -> str:
    if not value:
        return "—"
    from .models import utcnow

    seconds = int((utcnow() - as_utc(value)).total_seconds())
    if seconds < 60:
        return "دابا" if lang == "ar" else "à l'instant"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} د" if lang == "ar" else f"{minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} سا" if lang == "ar" else f"{hours} h"
    days = hours // 24
    return f"{days} يوم" if lang == "ar" else f"{days} j"


templates.env.filters["dzd"] = fmt_dzd
templates.env.filters["time"] = fmt_time
templates.env.globals["icon"] = icon
templates.env.globals["WILAYAS"] = WILAYAS
templates.env.globals["STAGES"] = STAGES
templates.env.globals["LANGS"] = LANGS
templates.env.globals["risk_level"] = risk_level
templates.env.globals["version"] = __version__
templates.env.globals["demo_mode"] = settings.demo_mode


def get_lang(request: Request) -> str:
    lang = request.session.get("lang") or settings.default_lang
    return lang if lang in LANGS else "ar"


def flash(request: Request, key: str, kind: str = "success", **kwargs) -> None:
    request.session.setdefault("flash", [])
    request.session["flash"] = request.session["flash"] + [{"key": key, "kind": kind, "args": kwargs}]


def render(request: Request, name: str, context: dict | None = None, status_code: int = 200):
    lang = get_lang(request)
    messages = request.session.pop("flash", []) if "flash" in request.session else []

    def t(key: str, **kwargs) -> str:
        return translate(key, lang, **kwargs)

    ctx = {
        "request": request,
        "lang": lang,
        "dir": LANGS[lang]["dir"],
        "t": t,
        "csrf": csrf_token(request),
        "flashes": [{"text": translate(m["key"], lang, **m.get("args", {})), "kind": m["kind"]} for m in messages],
        "wilaya_label": lambda code: wilaya_label(code, lang),
        "ago": lambda v: ago(v, lang),
        "path": request.url.path,
    }
    ctx.update(context or {})
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


class LoginRequired(Exception):
    pass


class CsrfFailed(Exception):
    pass


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise LoginRequired()
    user = db.get(User, user_id)
    if not user or not user.active:
        request.session.pop("user_id", None)
        raise LoginRequired()
    return user


def current_store(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Store:
    store = db.get(Store, user.store_id)
    if not store:
        raise LoginRequired()
    return store


def owner_only(user: User = Depends(current_user)) -> User:
    if user.role != "owner":
        raise HTTPException(status_code=403)
    return user


async def check_csrf(request: Request) -> None:
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        form = await request.form()
        if not csrf_ok(request, form.get("csrf")):
            raise CsrfFailed()


def scoped_order(db: Session, store: Store, order_id: str):
    from .models import Order

    order = db.scalar(select(Order).where(Order.id == order_id, Order.store_id == store.id))
    if not order:
        raise HTTPException(status_code=404)
    return order


def safe_text(value: str) -> Markup:
    """Line breaks preserved, everything else escaped."""
    from markupsafe import escape

    return Markup("<br>".join(escape(line) for line in (value or "").split("\n")))


templates.env.filters["lines"] = safe_text
