from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

_ASYNC_SCHEME = "postgresql+asyncpg"
_POSTGRES_SCHEMES = {"postgres", "postgresql", _ASYNC_SCHEME}
_DROPPED_PARAMS = {"channel_binding"}  # libpq-only; asyncpg rejects it


def to_async_url(url: str) -> str:
    """Turn a libpq-style URL (as Neon hands it out) into one SQLAlchemy+asyncpg accepts."""
    parts = urlsplit(url)
    scheme = _ASYNC_SCHEME if parts.scheme in _POSTGRES_SCHEMES else parts.scheme
    query = [
        ("ssl" if name == "sslmode" else name, value)
        for name, value in parse_qsl(parts.query)
        if name not in _DROPPED_PARAMS
    ]
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(
        to_async_url(url),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        # Neon's pooler is PgBouncer in transaction mode: named prepared statements must be unique per use.
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        },
    )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
