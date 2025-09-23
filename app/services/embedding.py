# app/services/embedding.py
import os
import json
import aiohttp
import logging
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("erp_ai.embedding")

# --- Supported OpenAI public models and their dims (keep in sync with DB) ---
_VALID_MODELS = {
    "text-embedding-3-small": 1536,
    # If you ever switch DB to 3072 dims, you can add:
    # "text-embedding-3-large": 3072,
}

# Read env, but clamp to a supported model & dims
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
_REQUESTED_MODEL = (os.getenv("EMBED_MODEL") or "text-embedding-3-small").strip()

if _REQUESTED_MODEL not in _VALID_MODELS:
    log.warning(
        "Unsupported EMBED_MODEL '%s'. Falling back to 'text-embedding-3-small'.",
        _REQUESTED_MODEL,
    )
    OPENAI_MODEL = "text-embedding-3-small"
else:
    OPENAI_MODEL = _REQUESTED_MODEL

EMBED_DIM = _VALID_MODELS[OPENAI_MODEL]  # should be 1536 for your DB

# Your DB schema enforces VECTOR(1536), so if someone changes the env to a
# 3072-d model without migrating DB, we’ll still pad/truncate to 1536 to avoid errors.
DB_VECTOR_DIM = 1536  # matches erp_ai.*.embedding VECTOR(1536)


def _zero_vec(n: int) -> list[float]:
    return [0.0] * n


def _coerce_dim(vec: list[float]) -> list[float]:
    """Ensure vector length matches DB constraint (1536)."""
    if not isinstance(vec, list):
        return _zero_vec(DB_VECTOR_DIM)
    if len(vec) == DB_VECTOR_DIM:
        return vec
    if len(vec) > DB_VECTOR_DIM:
        return vec[:DB_VECTOR_DIM]
    # pad
    return vec + [0.0] * (DB_VECTOR_DIM - len(vec))


async def embed_text(text: str) -> list[float]:
    """
    Create an embedding with OpenAI public API.
    - Uses OPENAI_API_KEY and OPENAI_MODEL.
    - On any error, returns a zero vector (length = DB_VECTOR_DIM).
    """
    # Safety: empty/short strings
    content = (text or "").strip()
    if not content:
        return _zero_vec(DB_VECTOR_DIM)

    # Require a valid OpenAI key
    if not OPENAI_API_KEY:
        log.warning("OPENAI_API_KEY not set; returning zero vector")
        return _zero_vec(DB_VECTOR_DIM)

    url = "https://api.openai.com/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        "input": content[:15000],  # keep payload reasonable
    }

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(url, headers=headers, data=json.dumps(payload)) as r:
                js = await r.json()
                if r.status >= 400:
                    # Common cause of your earlier error:
                    #  - Wrong model name -> invalid_request_error / invalid model ID
                    log.error("OpenAI embedding error %s: %s", r.status, js)
                    return _zero_vec(DB_VECTOR_DIM)

                vec = js["data"][0]["embedding"]
                vec = _coerce_dim(vec)
                return vec

    except Exception as e:
        log.error("embed_text failed: %s", e, exc_info=True)
        return _zero_vec(DB_VECTOR_DIM)
