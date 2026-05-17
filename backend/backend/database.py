import os
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_engine = None
_session_factory = None


def _init():
    global _engine, _session_factory
    if _engine is None:
        url = os.environ["DATABASE_URL"]
        _engine = create_async_engine(url, echo=False)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


def get_session_factory() -> async_sessionmaker:
    _init()
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    _init()
    async with _session_factory() as session:
        yield session
