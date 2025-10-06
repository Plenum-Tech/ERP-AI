# app/routers/extract.py
from __future__ import annotations

from typing import Optional, Callable, Dict, Any, List
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request, Query
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from datetime import datetime, date
import re, json

# per-type extractors
from app.di_extractors import invoice, id_document, bank_statement, receipt, generic_document

# asyncpg pool helpers
from app.db import db_conn

router = APIRouter(prefix="/extract", tags=["extract"])

# Map doc_type -> (analyze_url, analyze_bytes, to_dict, model_id)
EXTRACTORS: Dict[str, Dict[str, Callable[..., Any]]] = {
    "invoice":        {"analyze_url": invoice.analyze_invoice_url,          "analyze_bytes": invoice.analyze_invoice_bytes,          "to_dict": invoice.invoice_to_dict,          "model_id": lambda: invoice.MODEL_ID},
    "passport":       {"analyze_url": id_document.analyze_id_url,           "analyze_bytes": id_document.analyze_id_bytes,           "to_dict": id_document.id_to_dict,           "model_id": lambda: id_document.MODEL_ID},
    "visa":           {"analyze_url": id_document.analyze_id_url,           "analyze_bytes": id_document.analyze_id_bytes,           "to_dict": id_document.id_to_dict,           "model_id": lambda: id_document.MODEL_ID},
    "work_permit":    {"analyze_url": id_document.analyze_id_url,           "analyze_bytes": id_document.analyze_id_bytes,           "to_dict": id_document.id_to_dict,           "model_id": lambda: id_document.MODEL_ID},
    "bank_statement": {"analyze_url": bank_statement.analyze_bank_stmt_url, "analyze_bytes": bank_statement.analyze_bank_stmt_bytes,  "to_dict": bank_statement.bank_stmt_to_dict,  "model_id": lambda: bank_statement.MODEL_ID},
    "receipt":        {"analyze_url": receipt.analyze_receipt_url,          "analyze_bytes": receipt.analyze_receipt_bytes,          "to_dict": receipt.receipt_to_dict,          "model_id": lambda: receipt.MODEL_ID},
    "resume":         {"analyze_url": generic_document.analyze_generic_url, "analyze_bytes": generic_document.analyze_generic_bytes, "to_dict": generic_document.generic_to_dict, "model_id": lambda: generic_document.MODEL_ID},
    "injury_report":  {"analyze_url": generic_document.analyze_generic_url, "analyze_bytes": generic_document.analyze_generic_bytes, "to_dict": generic_document.generic_to_dict, "model_id": lambda: generic_document.MODEL_ID},
}

VALID_TYPES = list(EXTRACTORS.keys())

def _ensure_supported(doc_type: Optional[str]):
    if not doc_type:
        raise HTTPException(status_code=400, detail=f"'doc_type' is required. Valid: {VALID_TYPES}")
    if doc_type not in EXTRACTORS:
        raise HTTPException(status_code=400, detail=f"Unsupported doc_type '{doc_type}'. Valid: {VALID_TYPES}")

# ---------- parsing / normalization helpers ----------
def _to_snake(s: str) -> str:
    s = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", s)
    s = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.replace("__", "_").lower()

def _fval(fields: Dict[str, Any], key: str):
    obj = fields.get(key) or {}
    return obj.get("value")

_DATE_PATTERNS = [
    (r"^\d{4}-\d{2}-\d{2}$", "%Y-%m-%d"),
    (r"^\d{2}/\d{2}/\d{4}$", "%d/%m/%Y"),
    (r"^\d{2}-\d{2}-\d{4}$", "%d-%m-%Y"),
    (r"^\d{4}/\d{2}/\d{2}$", "%Y/%m/%d"),
    (r"^\d{2}\s+[A-Z]{3}\s+\d{4}$", "%d %b %Y"),   # 02 NOV 1975
    (r"^\d{2}\s+[A-Za-z]+\s+\d{4}$", "%d %B %Y"),  # 02 November 1975
]

def _to_date(v: Any) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    for rx, fmt in _DATE_PATTERNS:
        if re.match(rx, s):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        return None

def _to_num(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    try:
        return float(s)
    except Exception:
        return None

def _looks_like_address_dict(d: Dict[str, Any]) -> bool:
    addr_keys = {"houseNumber","poBox","road","street","streetAddress","unit","city","town","municipality","state","province","region","postalCode","zip","countryRegion","country"}
    return any(k in d for k in addr_keys)

def _flatten_address(d: Dict[str, Any]) -> str:
    parts = []
    for key in ["houseNumber","unit","poBox","street","road","streetAddress","city","town","municipality","state","province","region","postalCode","zip","countryRegion","country"]:
        val = d.get(key)
        if val:
            parts.append(str(val))
    if not parts and "content" in d:
        return str(d["content"])
    return ", ".join(parts) if parts else json.dumps(d, ensure_ascii=False)

def _to_text(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        try:
            flat = []
            for x in v:
                if isinstance(x, (dict, list, tuple)):
                    return json.dumps(v, ensure_ascii=False)
                flat.append("" if x is None else str(x))
            return ", ".join(flat)
        except Exception:
            return json.dumps(v, ensure_ascii=False)
    if isinstance(v, dict):
        if _looks_like_address_dict(v):
            return _flatten_address(v)
        if "content" in v and isinstance(v["content"], (str, int, float)):
            return str(v["content"])
        return json.dumps(v, ensure_ascii=False)
    return str(v)

# ---------- table typing rules ----------
TABLE_DATE_COLS = {
    "invoice_docs": {"invoice_date","due_date","service_start_date","service_end_date"},
    "bank_statement_docs": {"statement_start_date","statement_end_date"},
    "passport_docs": {"date_of_birth","date_of_issue","date_of_expiration"},
    "visa_docs": {"date_of_birth","date_of_issue","date_of_expiration"},
    "work_permit_docs": {"date_of_birth","date_of_issue","date_of_expiration"},
}
TABLE_NUM_COLS = {
    "invoice_docs": {"invoice_total","subtotal","total_tax","previous_unpaid_balance","amount_due"},
}
# Include key_value_pairs and tables for generic docs
TABLE_JSON_COLS = {
    "invoice_docs": {"fields","items"},
    "bank_statement_docs": {"fields","accounts"},
    "passport_docs": {"fields"},
    "visa_docs": {"fields"},
    "work_permit_docs": {"fields"},
    "resume_docs": {"fields","key_value_pairs","tables"},
    "injury_report_docs_docs": {"fields","key_value_pairs","tables"},
}

# Known scalar text columns per table
TEXT_COLS_BY_TABLE = {
    "invoice_docs": {
        "vendor_name","vendor_address","vendor_address_recipient",
        "customer_name","customer_id","customer_address","customer_address_recipient",
        "invoice_id","purchase_order",
        "billing_address","billing_address_recipient",
        "shipping_address","shipping_address_recipient",
        "service_address","service_address_recipient",
        "remittance_address","remittance_address_recipient",
    },
    "bank_statement_docs": {"account_holder_name","account_holder_address","bank_name","bank_address"},
    "passport_docs": {
        "document_type","country_region","region","first_name","last_name","full_name","document_number",
        "sex","nationality","address_text","machine_readable_zone","issuing_country","issuer","place_of_birth",
        "place_of_issue","personal_number",
    },
    "visa_docs": {
        "document_type","country_region","region","first_name","last_name","full_name","document_number",
        "sex","nationality","address_text","machine_readable_zone","visa_number","visa_type","entries",
        "duration_of_stay","issuing_country","issuer",
    },
    "work_permit_docs": {
        "document_type","country_region","region","first_name","last_name","full_name","document_number",
        "sex","nationality","address_text","machine_readable_zone","permit_number","permit_type","employer",
        "occupation","issuing_country","issuer",
    },
    "resume_docs": {"doc_inferred_type"},
    "injury_report_docs_docs": {"doc_inferred_type"},
}

PROVENANCE_COLS = ("model_id","source_filename","source_url","content_type")

def _apply_type(table: str, col: str, value: Any):
    if col in TABLE_DATE_COLS.get(table, set()):
        return _to_date(value)
    if col in TABLE_NUM_COLS.get(table, set()):
        return _to_num(value)
    return _to_text(value)

def _collect_dynamic_columns_from_fields(table: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    allowed = set(TEXT_COLS_BY_TABLE.get(table, set()))
    allowed |= TABLE_DATE_COLS.get(table, set())
    allowed |= TABLE_NUM_COLS.get(table, set())

    out: Dict[str, Any] = {}
    for k, obj in (fields or {}).items():
        val = (obj or {}).get("value")
        snk = _to_snake(k)
        if snk in allowed:
            out[snk] = val

    # derive full_name for ID docs if not returned explicitly
    if table in ("passport_docs","visa_docs","work_permit_docs") and "full_name" not in out:
        first = (fields.get("FirstName") or {}).get("value")
        last  = (fields.get("LastName")  or {}).get("value")
        if first or last:
            out["full_name"] = f"{first or ''} {last or ''}".strip() or None
    return out

async def _dynamic_insert(
    table: str,
    shaped: Dict[str, Any],
    *,
    model_id: str,
    source_filename: Optional[str],
    source_url: Optional[str],
    content_type: Optional[str],
    extra_fixed: Dict[str, Any] | None = None,
    extra_json: Dict[str, Any] | None = None,
) -> str:
    cols: list[str] = list(PROVENANCE_COLS)
    params: list[Any] = [model_id, source_filename, source_url, content_type]

    # extras (fixed scalars e.g. doc_inferred_type)
    if extra_fixed:
        for k, v in extra_fixed.items():
            cols.append(k)
            params.append(_apply_type(table, k, v))

    # dynamic from fields
    dyn = _collect_dynamic_columns_from_fields(table, shaped.get("fields", {}))
    for k, v in dyn.items():
        cols.append(k)
        params.append(_apply_type(table, k, v))

    # json payloads
    json_cols = TABLE_JSON_COLS.get(table, set())
    for k in sorted(json_cols):
        cols.append(k)
        payload = shaped.get(k, None)
        if extra_json and k in extra_json:
            payload = extra_json[k]
        if payload is None:
            payload = {} if k == "fields" else []
        params.append(json.dumps(payload, ensure_ascii=False))

    placeholders = ",".join(f"${i}" for i in range(1, len(params)+1))
    q = f"INSERT INTO erp_ai.{table} ({','.join(cols)}) VALUES ({placeholders}) RETURNING id;"

    async with db_conn() as conn:
        row_id = await conn.fetchval(q, *params)
    return str(row_id)

# ---------- Generic KVP fallback (no schema) ----------
# Extract multiple "Label: Value" segments from a single line.
# Example: "Project No.: 1023  Company Employee: Yes  Subcontractor Employee: No"
_SEGMENT_RE = re.compile(
    r"([A-Za-z0-9/().'’\-&, ]+?)\s*:\s*([^:]+?)(?=(?:\s+[A-Za-z].{0,30}?:|$))"
)

def _clean_label(lbl: str) -> str:
    s = (lbl or "").strip()
    s = re.sub(r"^\d+\.\s*", "", s)  # strip leading "5. "
    s = re.sub(r"\s+\.", ".", s)     # "No .:" -> "No.:"
    s = re.sub(r"\s+", " ", s)       # collapse whitespace
    return s

def _derive_kv_pairs_from_result(result_obj: Any) -> List[Dict[str, Any]]:
    pairs: List[Dict[str, Any]] = []
    pages = getattr(result_obj, "pages", []) or []
    for p in pages:
        for ln in getattr(p, "lines", []) or []:
            text = getattr(ln, "content", "") or ""
            if not text or ":" not in text:
                continue
            for m in _SEGMENT_RE.finditer(text):
                raw_label = m.group(1)
                value = m.group(2)
                key = _clean_label(raw_label)
                pairs.append({
                    "key": key,
                    "value": (value or "").strip() or None,
                    "key_confidence": None,
                    "value_confidence": None,
                })
    # Deduplicate identical (key,value) while preserving order
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for kv in pairs:
        sig = (kv["key"], kv["value"])
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(kv)
    return deduped

# ---------- ROUTE ----------
@router.post("")
async def extract_document(
    request: Request,
    doc_type_q: Optional[str] = Query(default=None, description=f"One of: {VALID_TYPES}"),
    doc_type_f: Optional[str] = Form(default=None, description=f"One of: {VALID_TYPES}"),
    file: Optional[UploadFile] = File(default=None),
    url_form: Optional[str] = Form(default=None),
    url_query: Optional[str] = Query(default=None),
):
    """
    Provide **doc_type** and either **file** or **url**.
    - Query: /extract?doc_type=invoice&url=...
    - Form:  doc_type=invoice, file=@...
    - JSON:  {"doc_type":"invoice","url":"https://..."}
    """
    # doc_type from form > query > JSON
    doc_type: Optional[str] = doc_type_f or doc_type_q
    url: Optional[str] = url_form or url_query
    if not doc_type or (not url and not file):
        if request.headers.get("content-type", "").startswith("application/json"):
            try:
                body = await request.json()
                doc_type = doc_type or body.get("doc_type")
                url = url or body.get("url")
            except Exception:
                pass

    _ensure_supported(doc_type)

    if not file and not url:
        raise HTTPException(status_code=400, detail="Provide either 'file' or 'url'.")
    if file and url:
        raise HTTPException(status_code=400, detail="Provide only one of 'file' or 'url', not both.")

    ex = EXTRACTORS[doc_type]  # type: ignore
    to_dict = ex["to_dict"]
    model_id = ex["model_id"]()

    data: Optional[bytes] = None
    content_type: Optional[str] = None
    source_filename: Optional[str] = None
    source_url: Optional[str] = None

    if file:
        source_filename = file.filename
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        content_type = getattr(file, "content_type", None)

    try:
        # Run the selected model
        if data is not None:
            try:
                result = ex["analyze_bytes"](data, content_type)  # type: ignore
            except TypeError:
                result = ex["analyze_bytes"](data)  # type: ignore
        else:
            if not url or not url.strip():
                raise HTTPException(status_code=400, detail="URL is empty.")
            source_url = url.strip()
            result = ex["analyze_url"](source_url)  # type: ignore

        shaped = to_dict(result, doc_kind=doc_type) if doc_type in ("passport","visa","work_permit") else to_dict(result)

        # ---------- Generic KVP fallback for layout-only docs ----------
        # If prebuilt-layout gave no kv_pairs (common for templates / plain lines),
        # derive generic key:value pairs directly from the recognized lines.
        if doc_type in ("resume", "injury_report"):
            if not shaped.get("key_value_pairs"):
                kv_fallback = _derive_kv_pairs_from_result(result)
                if kv_fallback:
                    shaped.setdefault("key_value_pairs", kv_fallback)
            # Ensure defaults exist so downstream JSON columns are never null
            shaped.setdefault("fields", {})
            shaped.setdefault("tables", [])

        # ---- Persist to your tables (asyncpg) ----
        if doc_type == "invoice":
            row_id = await _dynamic_insert(
                table="invoice_docs",
                shaped=shaped,
                model_id=model_id,
                source_filename=source_filename,
                source_url=source_url,
                content_type=content_type,
                extra_json={"fields": shaped.get("fields", {}), "items": shaped.get("items", [])},
            )
        elif doc_type == "bank_statement":
            row_id = await _dynamic_insert(
                table="bank_statement_docs",
                shaped=shaped,
                model_id=model_id,
                source_filename=source_filename,
                source_url=source_url,
                content_type=content_type,
                extra_json={"fields": shaped.get("fields", {}), "accounts": shaped.get("accounts", [])},
            )
        elif doc_type == "passport":
            row_id = await _dynamic_insert(
                table="passport_docs",
                shaped=shaped,
                model_id=model_id,
                source_filename=source_filename,
                source_url=source_url,
                content_type=content_type,
                extra_json={"fields": shaped.get("fields", {})},
            )
        elif doc_type == "visa":
            row_id = await _dynamic_insert(
                table="visa_docs",
                shaped=shaped,
                model_id=model_id,
                source_filename=source_filename,
                source_url=source_url,
                content_type=content_type,
                extra_json={"fields": shaped.get("fields", {})},
            )
        elif doc_type == "work_permit":
            row_id = await _dynamic_insert(
                table="work_permit_docs",
                shaped=shaped,
                model_id=model_id,
                source_filename=source_filename,
                source_url=source_url,
                content_type=content_type,
                extra_json={"fields": shaped.get("fields", {})},
            )
        elif doc_type == "resume":
            row_id = await _dynamic_insert(
                table="resume_docs",
                shaped=shaped,
                model_id=model_id,
                source_filename=source_filename,
                source_url=source_url,
                content_type=content_type,
                extra_fixed={"doc_inferred_type": shaped.get("doc_type")},
                extra_json={
                    "fields": shaped.get("fields", {}),
                    "key_value_pairs": shaped.get("key_value_pairs", []),
                    "tables": shaped.get("tables", []),
                },
            )
        elif doc_type == "injury_report":
            row_id = await _dynamic_insert(
                table="injury_report_docs_docs",
                shaped=shaped,
                model_id=model_id,
                source_filename=source_filename,
                source_url=source_url,
                content_type=content_type,
                extra_fixed={"doc_inferred_type": shaped.get("doc_type")},
                extra_json={
                    "fields": shaped.get("fields", {}),
                    "key_value_pairs": shaped.get("key_value_pairs", []),
                    "tables": shaped.get("tables", []),
                },
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported doc_type '{doc_type}'")

        return {"doc_type": doc_type, "model_id": model_id, "row_id": row_id, "result": shaped}

    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=("Document Intelligence returned 404 (Resource not found). "
                    f"Verify your endpoint/key and model availability for '{doc_type}'. "
                    "Endpoint must be https://<name>.cognitiveservices.azure.com"),
        ) from e
    except HttpResponseError as e:
        status = getattr(e, "status_code", None) or 502
        message = getattr(e, "message", None) or "Service error from Document Intelligence."
        raise HTTPException(status_code=status, detail=message) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
