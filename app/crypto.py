"""Encrypt the merchant's third-party secrets (WhatsApp token, app secret, Gemini key) at rest,
with a key derived from SECRET_KEY. Changing SECRET_KEY makes saved secrets unreadable: they then
read as empty and the merchant pastes them again."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

PREFIX = "enc:"
_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(("mrigel-secrets:" + settings.secret_key).encode()).digest()))


def encrypt(value: str) -> str:
    if not value or value.startswith(PREFIX):
        return value
    return PREFIX + _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value or not value.startswith(PREFIX):
        return value or ""
    try:
        return _fernet.decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        return ""
