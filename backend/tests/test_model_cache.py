from backend.app.services.model_cache import (
    decrypt_secret,
    encrypt_secret,
    mask_secret,
)


def test_encrypt_decrypt_roundtrip():
    token = encrypt_secret("sk-secret-1234")
    assert token is not None and token != "sk-secret-1234"
    assert decrypt_secret(token) == "sk-secret-1234"


def test_encrypt_none_returns_none():
    assert encrypt_secret(None) is None
    assert decrypt_secret(None) is None


def test_mask_secret():
    assert mask_secret("sk-abcdefgh") == "••••efgh"
    assert mask_secret(None) is None
