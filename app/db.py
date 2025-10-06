# app/db.py
from dotenv import load_dotenv; load_dotenv()
import os
import ssl as _ssl
import asyncpg
import logging
from contextlib import asynccontextmanager

log = logging.getLogger("erp_ai.db")

DB_URL = os.getenv("DATABASE_URL")  # e.g. postgresql://user:pass@host:5432/erp_ai
POOL_MIN_SIZE = int(os.getenv("DB_POOL_MIN", "1"))
POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX", "10"))
STATEMENT_CACHE_SIZE = int(os.getenv("DB_STMT_CACHE", "100"))
# DATABASE_SSL: "disable" (default), "require", or "verify-full" (requires system certs)
DATABASE_SSL = os.getenv("DATABASE_SSL", "disable").lower()

_POOL: asyncpg.Pool | None = None


def _ssl_ctx():
    if DATABASE_SSL == "disable":
        return None
    if DATABASE_SSL == "require":
        ctx = _ssl.create_default_context()
        # do NOT verify hostname or cert chain (server must support TLS)
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        return ctx
    if DATABASE_SSL == "verify-full":
        # strict verification (hostname + CA trust)
        return _ssl.create_default_context()
    # fallback
    return None


async def init_db_pool() -> None:
    """Create a global asyncpg pool. Call this on startup."""
    global _POOL
    if _POOL is not None:
        return
    if not DB_URL:
        log.error("DATABASE_URL not set")
        raise RuntimeError("DATABASE_URL is not set")

    log.info(
        "Creating asyncpg pool (min=%s max=%s stmt_cache=%s ssl=%s)",
        POOL_MIN_SIZE, POOL_MAX_SIZE, STATEMENT_CACHE_SIZE, DATABASE_SSL
    )
    _POOL = await asyncpg.create_pool(
        dsn=DB_URL,
        min_size=POOL_MIN_SIZE,
        max_size=POOL_MAX_SIZE,
        statement_cache_size=STATEMENT_CACHE_SIZE,
        ssl=_ssl_ctx(),
    )


async def close_db_pool() -> None:
    """Close the global pool. Call this on shutdown."""
    global _POOL
    if _POOL is not None:
        await _POOL.close()
        _POOL = None


async def _ensure_pool():
    if _POOL is None:
        await init_db_pool()


async def get_conn() -> asyncpg.Connection:
    """
    Get a single connection from the pool (caller must release!) —
    prefer using `async with db_conn() as conn:` instead of calling this directly.
    """
    await _ensure_pool()
    assert _POOL is not None  # for type checkers
    try:
        return await _POOL.acquire()
    except Exception as e:
        log.exception("DB acquire failed: %s", e)
        raise


@asynccontextmanager
async def db_conn():
    """
    Context manager that acquires and releases a pooled connection safely.
    Usage:
        async with db_conn() as conn:
            await conn.execute("SELECT 1")
    """
    conn = await get_conn()
    try:
        yield conn
    finally:
        try:
            assert _POOL is not None
            await _POOL.release(conn)
        except Exception as e:
            log.warning("DB release failed: %s", e)


# ---------- Convenience helpers (optional) ----------

async def fetchval(query: str, *args):
    async with db_conn() as conn:
        return await conn.fetchval(query, *args)

async def fetchrow(query: str, *args):
    async with db_conn() as conn:
        return await conn.fetchrow(query, *args)

async def fetch(query: str, *args):
    async with db_conn() as conn:
        return await conn.fetch(query, *args)

async def execute(query: str, *args):
    async with db_conn() as conn:
        return await conn.execute(query, *args)
