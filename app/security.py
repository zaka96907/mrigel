"""Passwords, sessions and CSRF."""

import hmac
import secrets

import bcrypt
from fastapi import Request


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(24)
        request.session["csrf"] = token
    return token


def csrf_ok(request: Request, submitted: str | None) -> bool:
    expected = request.session.get("csrf")
    header = request.headers.get("x-csrf-token")
    candidate = submitted or header or ""
    return bool(expected) and hmac.compare_digest(expected, candidate)
