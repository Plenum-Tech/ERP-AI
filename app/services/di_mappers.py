"""
Map DI v4.0 AnalyzeResult to geometry-free, canonical JSON by doc_type.
We always return: {"doc_type", "model_id", "quality", "summary", "line_items", "raw_fields"}
- quality: "ok" | "degraded" (used when we had to fallback to a generic model)
"""
from typing import Any, Dict, List, Optional

def _field(fields: Dict[str, Any], name: str):
    f = fields.get(name)
    return getattr(f, "value", None) if f else None

def _shape_invoice(res: Any) -> Dict[str, Any]:
    docs = res.documents or []
    doc  = docs[0] if docs else None
    fields = doc.fields if doc else {}
    out = {
        "summary": {
            "vendor_name": _field(fields, "VendorName"),
            "vendor_tax_id": _field(fields, "VendorTaxId"),
            "customer_name": _field(fields, "CustomerName"),
            "invoice_number": _field(fields, "InvoiceId") or _field(fields, "InvoiceNumber"),
            "purchase_order_number": _field(fields, "PurchaseOrder"),
            "invoice_date": _field(fields, "InvoiceDate"),
            "due_date": _field(fields, "DueDate"),
            "sub_total": _field(fields, "SubTotal"),
            "total_tax": _field(fields, "TotalTax"),
            "amount_due": _field(fields, "AmountDue"),
            "billing_address": _field(fields, "BillingAddress"),
            "shipping_address": _field(fields, "ShippingAddress"),
            "remittance_address": _field(fields, "RemittanceAddress"),
        },
        "line_items": [],
        "raw_fields": {},
    }
    items = fields.get("Items")
    if items and items.value:
        for it in items.value:
            props = it.properties or {}
            def pv(n):
                f = props.get(n)
                return getattr(f, "value", None) if f else None
            out["line_items"].append({
                "description": pv("Description"),
                "quantity": pv("Quantity"),
                "unit_price": pv("UnitPrice"),
                "amount": pv("Amount"),
                "product_code": pv("ProductCode"),
                "tax": pv("Tax"),
            })
    for k, f in fields.items():
        out["raw_fields"][k] = {
            "value": getattr(f, "value", None),
            "content": getattr(f, "content", None),
            "confidence": getattr(f, "confidence", None),
        }
    return out

def _shape_id_document(res: Any) -> Dict[str, Any]:
    docs = res.documents or []
    doc  = docs[0] if docs else None
    fields = doc.fields if doc else {}
    # Covers passport, visa, work permits (same model)
    # Common fields (names are per DI schema; keep generic)
    out = {
        "summary": {
            "document_type": _field(fields, "DocumentType"),
            "country_region": _field(fields, "CountryRegion"),
            "document_number": _field(fields, "DocumentNumber"),
            "first_name": _field(fields, "FirstName"),
            "last_name": _field(fields, "LastName"),
            "full_name": _field(fields, "FullName"),
            "date_of_birth": _field(fields, "DateOfBirth"),
            "date_of_issue": _field(fields, "DateOfIssue"),
            "date_of_expiry": _field(fields, "DateOfExpiration") or _field(fields, "DateOfExpiry"),
            "sex": _field(fields, "Sex"),
            "nationality": _field(fields, "Nationality"),
            "mrz": _field(fields, "MachineReadableZone"),
            "address": _field(fields, "Address"),
        },
        "line_items": [],
        "raw_fields": {},
    }
    for k, f in fields.items():
        out["raw_fields"][k] = {
            "value": getattr(f, "value", None),
            "content": getattr(f, "content", None),
            "confidence": getattr(f, "confidence", None),
        }
    return out

def _shape_bank_statement(res: Any) -> Dict[str, Any]:
    # If we actually hit prebuilt-bankStatement.us, fields are richer; for fallback we’ll just generalize.
    docs = res.documents or []
    doc  = docs[0] if docs else None
    fields = doc.fields if doc else {}
    out = {
        "summary": {
            "bank_name": _field(fields, "BankName"),
            "account_holder": _field(fields, "AccountHolderName") or _field(fields, "CustomerName"),
            "account_number": _field(fields, "AccountNumber"),
            "statement_period_start": _field(fields, "StatementStartDate"),
            "statement_period_end": _field(fields, "StatementEndDate"),
            "opening_balance": _field(fields, "OpeningBalance"),
            "closing_balance": _field(fields, "ClosingBalance"),
            "currency": _field(fields, "Currency"),
        },
        "line_items": [],
        "raw_fields": {},
    }
    # Transactions array may be under "Transactions"
    txs = fields.get("Transactions")
    if txs and txs.value:
        for t in txs.value:
            props = t.properties or {}
            def pv(n):
                f = props.get(n)
                return getattr(f, "value", None) if f else None
            out["line_items"].append({
                "date": pv("Date"),
                "description": pv("Description"),
                "amount": pv("Amount"),
                "balance": pv("Balance"),
                "type": pv("Type"),
                "reference": pv("Reference"),
            })
    for k, f in fields.items():
        out["raw_fields"][k] = {
            "value": getattr(f, "value", None),
            "content": getattr(f, "content", None),
            "confidence": getattr(f, "confidence", None),
        }
    return out

def _shape_generic(res: Any) -> Dict[str, Any]:
    # For resume/injury_report/others using prebuilt-document
    docs = res.documents or []
    doc  = docs[0] if docs else None
    fields = getattr(doc, "fields", {}) or {}
    out = {
        "summary": {
            "title": _field(fields, "Title"),
            "author": _field(fields, "Author"),
            "date": _field(fields, "Date"),
        },
        "line_items": [],
        "raw_fields": {},
    }
    # Put all fields into raw_fields for audit
    for k, f in fields.items():
        out["raw_fields"][k] = {
            "value": getattr(f, "value", None),
            "content": getattr(f, "content", None),
            "confidence": getattr(f, "confidence", None),
        }
    return out

def shape_output(doc_type: str, res: Any, *, model_id: str, degraded: bool = False) -> Dict[str, Any]:
    base = {
        "doc_type": doc_type,
        "model_id": model_id,
        "quality": "degraded" if degraded else "ok",
        "api_version": getattr(res, "api_version", None),
    }
    if doc_type == "invoice":
        base.update(_shape_invoice(res))
    elif doc_type in ("passport", "visa", "work_permit"):
        base.update(_shape_id_document(res))
    elif doc_type == "bank_statement":
        base.update(_shape_bank_statement(res))
    else:  # resume, injury_report, etc.
        base.update(_shape_generic(res))
    return base
