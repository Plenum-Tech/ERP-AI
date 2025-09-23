from dotenv import load_dotenv; load_dotenv()
import os, asyncpg
from app.core.errors import error_response
import logging
log = logging.getLogger("erp_ai.db")

DB_URL = os.getenv("DATABASE_URL")

async def get_conn() -> asyncpg.Connection:
    if not DB_URL:
        # Let caller handle; we log here for visibility
        log.error("DATABASE_URL not set")
        raise RuntimeError("DATABASE_URL is not set")
    try:
        conn = await asyncpg.connect(dsn=DB_URL)
        return conn
    except Exception as e:
        log.exception("DB connect failed: %s", e)
        # Raise to be handled by route try/except
        raise
