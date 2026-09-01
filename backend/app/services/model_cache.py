# prism/backend/app/services/model_cache.py
import base64
import hashlib

from backend.app.config import settings


def _fernet():
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(hashlib.sha256(settings.JWT_SECRET.encode()).digest())
    return Fernet(key)


def encrypt_secret(plain: str | None) -> str | None:
    if not plain:
        return None
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str | None) -> str | None:
    if not token:
        return None
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")


def mask_secret(plain: str | None) -> str | None:
    if not plain:
        return None
    return f"••••{plain[-4:]}"
