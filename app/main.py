"""Mrigel web app. Run: uvicorn app.main:app --reload"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import jobs
from .config import settings
from .db import init_db
from .routes import api, pages, public
from .web import CsrfFailed, LoginRequired, flash, render

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("mrigel")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if settings.demo_mode:
        from .db import session_scope
        from .seed import ensure_demo

        with session_scope() as db:
            ensure_demo(db)
    task = asyncio.create_task(jobs.loop()) if settings.run_jobs_in_process else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Mrigel", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, session_cookie="mrigel_session",
                   max_age=60 * 60 * 24 * 14, same_site="lax", https_only=settings.secure_cookies)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self' https://wa.me https://api.whatsapp.com",
    )
    return response


app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.include_router(public.router)
app.include_router(pages.router)
app.include_router(api.router)


def _wants_json(request: Request) -> bool:
    return request.url.path.startswith(("/api/", "/webhooks/", "/tasks/"))


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, _exc):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(CsrfFailed)
async def _csrf_failed(request: Request, _exc):
    flash(request, "err_csrf", "error")
    return RedirectResponse(request.url.path if request.method == "GET" else "/dashboard", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if _wants_json(request):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    key = {404: "not_found", 403: "forbidden", 429: "too_many"}.get(exc.status_code, "error_generic")
    return render(request, "error.html", {"message_key": key, "code": exc.status_code}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    if _wants_json(request):
        return JSONResponse({"error": "invalid request", "details": exc.errors()}, status_code=422)
    return render(request, "error.html", {"message_key": "err_fields", "code": 400}, status_code=400)


@app.exception_handler(Exception)
async def _unexpected(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    if _wants_json(request):
        return JSONResponse({"error": "internal error"}, status_code=500)
    return render(request, "error.html", {"message_key": "error_generic", "code": 500}, status_code=500)
