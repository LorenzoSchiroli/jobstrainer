import os
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError  # noqa: F401

ALGORITHM = "HS256"


def _secret() -> str:
    return os.environ["SECRET_KEY"]


def _expire_days() -> int:
    return int(os.getenv("ACCESS_TOKEN_EXPIRE_DAYS", "7"))


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=_expire_days())
    return jwt.encode({"sub": user_id, "exp": expire}, _secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    return payload["sub"]
