import pytest
from jose import JWTError
from backend.auth.jwt import create_access_token, decode_access_token


def test_create_and_decode_roundtrip():
    token = create_access_token("user-id-123")
    assert decode_access_token(token) == "user-id-123"


def test_decode_invalid_token_raises():
    with pytest.raises(JWTError):
        decode_access_token("not.a.valid.token")


def test_decode_tampered_token_raises():
    token = create_access_token("user-id-456")
    tampered = token[:-4] + "XXXX"
    with pytest.raises(JWTError):
        decode_access_token(tampered)
