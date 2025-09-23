from fastapi import APIRouter, Query
from app.db import get_conn
from app.core.errors import error_response
from app.services.embedding import embed_text
import logging

log = logging.getLogger("erp_ai.search")
router = APIRouter()

TABLES = [
    ("passport","erp_ai.passport_docs"),
    ("visa","erp_ai.visa_docs"),
    ("work_permit","erp_ai.work_permit_docs"),
    ("resume","erp_ai.resume_docs"),
    ("bank_statement","erp_ai.bank_statement_docs"),
    ("invoice","erp_ai.invoice_docs"),
    ("injury_report","erp_ai.injury_report_docs"),
]

@router.get("/search")
async def search(q: str = Query(...), k: int = 10):
    try:
        if not q:
            return error_response("Query 'q' is required", 400, "EBADQUERY")

        qvec = await embed_text(q)

        union = " UNION ALL ".join([
            f"""
            SELECT '{doc_type}'::text AS doc_type, id, file_name,
                   1 - (embedding <=> $1) AS score
            FROM {tbl}
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> $1
            LIMIT {k}
            """
            for doc_type, tbl in TABLES
        ])

        conn = await get_conn()
        try:
            rows = await conn.fetch(f"SELECT * FROM ({union}) x ORDER BY score DESC LIMIT $2", qvec, k)
        finally:
            await conn.close()

        return {
            "ok": True,
            "results": [
                {"doc_type": r["doc_type"], "id": str(r["id"]), "file_name": r["file_name"], "score": float(r["score"])}
                for r in rows
            ],
        }
    except Exception as e:
        log.exception("Search failed: %s", e)
        return error_response("Search failed", 500, "ESEARCH", str(e))
