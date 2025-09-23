from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from app.db import get_conn
from app.core.errors import error_response
import hashlib, time, logging

log = logging.getLogger("erp_ai.upload")
router = APIRouter()

TABLE_BY_TYPE = {
    "passport": "erp_ai.passport_docs",
    "visa": "erp_ai.visa_docs",
    "work_permit": "erp_ai.work_permit_docs",
    "resume": "erp_ai.resume_docs",
    "bank_statement": "erp_ai.bank_statement_docs",
    "invoice": "erp_ai.invoice_docs",
    "injury_report": "erp_ai.injury_report_docs",
}

@router.post("/upload")
async def upload(
    doc_type: str = Form(...),
    external_ref: str | None = Form(None),
    file: UploadFile = File(...),
):
    if doc_type not in TABLE_BY_TYPE:
        return error_response(f"Unsupported doc_type '{doc_type}'", 400, "EBADTYPE")

    try:
        content = await file.read()
        if not content:
            return error_response("Empty file", 400, "EEMPTY")
        sha = hashlib.sha256(content).hexdigest()
        blob_url = f"blob://placeholder/{int(time.time())}/{file.filename}"  # TODO: Azure Blob

        conn = await get_conn()
        try:
            row = await conn.fetchrow(
                f"""
                INSERT INTO {TABLE_BY_TYPE[doc_type]}
                    (external_ref, blob_url, file_name, mime_type, size_bytes, file_sha256, status)
                VALUES ($1,$2,$3,$4,$5,$6,'uploaded')
                RETURNING id
                """,
                external_ref, blob_url, file.filename, file.content_type, len(content), sha
            )
        finally:
            await conn.close()

        return {"ok": True, "id": str(row["id"]), "blob_url": blob_url, "sha256": sha}

    except Exception as e:
        log.exception("Upload failed: %s", e)
        return error_response("Upload failed", 500, "EUPLOAD", str(e))
