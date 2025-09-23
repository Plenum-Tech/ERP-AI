from fastapi import APIRouter, UploadFile, File, Form
from app.db import get_conn
from app.core.errors import error_response
from app.services.azure_di import analyze
from app.services.text import flatten_text
from app.services.embedding import embed_text
import logging, json, re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

log = logging.getLogger("erp_ai.extract")
router = APIRouter()

TBL = {
    "passport":       "erp_ai.passport_docs",
    "visa":           "erp_ai.visa_docs",
    "work_permit":    "erp_ai.work_permit_docs",
    "resume":         "erp_ai.resume_docs",
    "bank_statement": "erp_ai.bank_statement_docs",
    "invoice":        "erp_ai.invoice_docs",
    "injury_report":  "erp_ai.injury_report_docs",
}

# ---------- helpers ----------
def _doc_fields(di_json: dict):
    try:
        docs = (di_json.get("analyzeResult", {}) or {}).get("documents", []) or []
        return (docs[0].get("fields", {}) if docs else {}) or {}
    except Exception:
        return {}

def _val(field_obj):
    """Return best-typed value from a DI field object."""
    if not isinstance(field_obj, dict):
        return None
    # try typed first
    for k in ("valueString", "valueDate", "valueTime", "valuePhoneNumber", "valueNumber"):
        if k in field_obj and field_obj[k] is not None:
            return field_obj[k]
    # currency
    if "valueCurrency" in field_obj and isinstance(field_obj["valueCurrency"], dict):
        vc = field_obj["valueCurrency"]
        # return (amount, currencyCode)
        amt = vc.get("amount")
        ccy = vc.get("currencyCode") or vc.get("currencySymbol")
        if amt is not None:
            return {"amount": amt, "currency": ccy}
    # fallback to content
    return field_obj.get("content")

def _get(di_json: dict, name: str):
    return _val(_doc_fields(di_json).get(name))

def _to_vector_literal(vec) -> str | None:
    try:
        if not vec or not isinstance(vec, (list, tuple)):
            return None
        return "[" + ",".join(str(float(x)) for x in vec) + "]"
    except Exception:
        return None

_DATE_PATTERNS = [
    "%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y",
    "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y",
]

def _parse_date(val) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s: return None
    s = re.sub(r"(\d{1,2})(st|nd|rd|th)\b", r"\1", s, flags=re.IGNORECASE)
    for fmt in _DATE_PATTERNS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    if m:
        try: return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception: pass
    return None

_CURRENCY_RE = re.compile(r"[^\d\.\-]")
def _parse_decimal(val) -> Decimal | None:
    if val is None: return None
    if isinstance(val, (int, float, Decimal)):
        try: return Decimal(val)
        except Exception: return None
    s = str(val).strip()
    if not s: return None
    s = s.replace(",", "")
    s = _CURRENCY_RE.sub("", s)
    try: return Decimal(s)
    except (InvalidOperation, ValueError): return None

def _json_default(o):
    if isinstance(o, Decimal):   return float(o)
    if isinstance(o, (datetime, date)): return o.isoformat()
    return str(o)

def _json_dump(val) -> str | None:
    if val is None: return None
    return json.dumps(val, default=_json_default)

JSON_COLS = {
    "extracted_json",
    "entities_json",
    "skills",
    "education",
    "experience",
    "certifications",
    "transactions_json",
    "line_items_json",
}

# ---------- endpoint ----------
@router.post("/extract")
async def extract(
    doc_type: str = Form(...),
    id: str = Form(...),
    file: UploadFile = File(...),
):
    if doc_type not in TBL:
        return error_response(f"Unsupported doc_type '{doc_type}'", 400, "EBADTYPE")

    try:
        content = await file.read()
        if not content:
            return error_response("Empty file", 400, "EEMPTY")

        di = await analyze(doc_type, content, file.content_type or "application/pdf")
        text = flatten_text(di)
        emb_literal = _to_vector_literal(await embed_text(text or " "))

        updates: dict[str, object] = {
            "status":         "extracted",
            "di_model":       "prebuilt-document",
            "extracted_json": di,
            "text_full":      text,
            "embedding":      emb_literal,
        }

        if doc_type == "invoice":
            # pull typed fields
            inv_id      = _get(di, "InvoiceId")
            inv_date    = _parse_date(_get(di, "InvoiceDate"))
            due_date    = _parse_date(_get(di, "DueDate"))
            po_number   = _get(di, "PurchaseOrder")
            vendor_name = _get(di, "VendorName")
            vendor_tax  = _get(di, "VendorTaxId")
            cust_name   = _get(di, "CustomerName")
            cust_addr   = _get(di, "CustomerAddress")  # string content
            bill_addr   = _get(di, "BillingAddress") or _get(di, "CustomerAddress")
            ship_addr   = _get(di, "ShippingAddress")

            subtotal_v  = _get(di, "SubTotal") or _get(di, "Subtotal")
            total_tax_v = _get(di, "TotalTax") or _get(di, "Tax")
            total_v     = _get(di, "Total") or _get(di, "AmountDue")

            # amounts may come as numbers or {amount,currency}
            def pick_amount(x):
                if isinstance(x, dict) and "amount" in x:
                    return _parse_decimal(x.get("amount"))
                return _parse_decimal(x)

            def pick_currency(*vals):
                for v in vals:
                    if isinstance(v, dict) and v.get("currency"):
                        return v.get("currency")
                # heuristic fallback from OCR text (GBP, USD, EUR)
                m = re.search(r"\b(USD|EUR|GBP|AED|INR|CAD|AUD)\b", text or "", re.I)
                return (m.group(1).upper() if m else None)

            subtotal = pick_amount(subtotal_v)
            total_tax = pick_amount(total_tax_v)
            total = pick_amount(total_v)
            currency = pick_currency(subtotal_v, total_v, total_tax_v)

            # items
            lines = None
            try:
                docs = (di.get("analyzeResult", {}) or {}).get("documents", []) or []
                if docs:
                    f = (docs[0].get("fields", {}) or {})
                    items = f.get("Items", {})
                    if isinstance(items, dict) and isinstance(items.get("valueArray"), list):
                        lines = []
                        for idx, it in enumerate(items["valueArray"], start=1):
                            vo = it.get("valueObject", {}) or {}
                            def obj(n): return _val(vo.get(n))
                            qty  = pick_amount(obj("Quantity"))
                            up   = pick_amount(obj("UnitPrice"))
                            amt  = pick_amount(obj("Amount"))
                            lines.append({
                                "line_no":     idx,
                                "description": obj("Description"),
                                "quantity":    qty,
                                "unit":        obj("Unit"),
                                "unit_price":  up,
                                "amount":      amt,
                            })
            except Exception as e:
                log.warning("Invoice line parse warn: %s", e)

            updates.update({
                "di_model":              "prebuilt-invoice",
                "invoice_number":        inv_id,
                "invoice_date":          inv_date,
                "due_date":              due_date,
                "vendor_name":           vendor_name,
                "vendor_tax_id":         vendor_tax,
                "customer_name":         cust_name,
                "billing_address":       bill_addr,
                "shipping_address":      ship_addr,
                "purchase_order_number": po_number,
                "currency":              currency,
                "subtotal_amount":       subtotal,
                "tax_amount":            total_tax,
                "total_amount":          total,
                "line_items_json":       lines,
            })

        elif doc_type == "passport":
            from_fields = {
                "passport_number": _get(di, "DocumentNumber"),
                "first_name":      _get(di, "FirstName"),
                "last_name":       _get(di, "LastName"),
                "expiry_date":     _parse_date(_get(di, "DateOfExpiration")),
                "country":         _get(di, "CountryRegion"),
            }
            updates.update({"di_model": "prebuilt-idDocument", **from_fields})

        elif doc_type == "visa":
            from_fields = {
                "visa_number":     _get(di, "VisaNumber") or _get(di, "DocumentNumber"),
                "category":        _get(di, "Category"),
                "issued_date":     _parse_date(_get(di, "DateOfIssue")),
                "expiry_date":     _parse_date(_get(di, "DateOfExpiration")),
                "issuing_country": _get(di, "CountryRegion"),
                "holder_name":     ( (_get(di,"FirstName") or "") + " " + (_get(di,"LastName") or "") ).strip(),
            }
            updates.update({"di_model": "prebuilt-idDocument", **from_fields})

        elif doc_type == "work_permit":
            from_fields = {
                "permit_number": _get(di, "DocumentNumber"),
                "holder_name":   ( (_get(di,"FirstName") or "") + " " + (_get(di,"LastName") or "") ).strip(),
                "employer_name": _get(di, "Employer") or _get(di, "Organization"),
                "job_title":     _get(di, "Profession") or _get(di, "JobTitle"),
                "issued_date":   _parse_date(_get(di, "DateOfIssue")),
                "expiry_date":   _parse_date(_get(di, "DateOfExpiration")),
            }
            updates.update({"di_model": "prebuilt-idDocument", **from_fields})

        elif doc_type == "resume":
            updates.update({
                "di_model":       "prebuilt-document",
                "candidate_name": _get(di, "PersonName"),
                "email":          _get(di, "Email") or _get(di, "EmailAddress"),
                "phone":          _get(di, "PhoneNumber"),
            })

        elif doc_type == "bank_statement":
            updates.update({"di_model": "prebuilt-bankStatement"})

        elif doc_type == "injury_report":
            updates.update({
                "di_model":            "prebuilt-document",
                "injured_person_name": _get(di, "PersonName"),
                "incident_date":       _parse_date(_get(di, "Date") or _get(di, "IncidentDate")),
                "location":            _get(di, "Location"),
                "injury_type":         _get(di, "InjuryType"),
                "body_part":           _get(di, "BodyPart"),
                "severity":            _get(di, "Severity"),
                "notes":               _get(di, "Notes"),
            })

        # ---------- dynamic UPDATE ----------
        items = list(updates.items())
        assignments, params = [], []

        JSON_COLS = {
            "extracted_json","entities_json","skills","education","experience",
            "certifications","transactions_json","line_items_json"
        }

        for col, val in items:
            if col == "embedding":
                if val is None:
                    assignments.append("embedding = NULL")
                else:
                    assignments.append(f"{col} = ${len(params)+1}::vector")
                    params.append(val)
                continue

            if col in JSON_COLS:
                assignments.append(f"{col} = ${len(params)+1}::jsonb")
                params.append(json.dumps(val, default=lambda o:
                    float(o) if isinstance(o, Decimal)
                    else o.isoformat() if isinstance(o, (datetime, date))
                    else o
                ) if val is not None else None)
                continue

            assignments.append(f"{col} = ${len(params)+1}")
            params.append(val)

        assignments.append("updated_at = NOW()")
        where_idx = len(params) + 1
        sql = f"UPDATE {TBL[doc_type]} SET " + ", ".join(assignments) + f" WHERE id = ${where_idx}"
        params.append(id)

        log.info("SQL template: %s | params=%d", sql, len(params))

        conn = await get_conn()
        try:
            await conn.execute(sql, *params)
        finally:
            await conn.close()

        return {"ok": True, "id": id, "chars": len(text or ""), "embedded": emb_literal is not None}

    except Exception as e:
        log.exception("Extract failed: %s", e)
        return error_response("Extraction failed", 500, "EEXTRACT", str(e))
