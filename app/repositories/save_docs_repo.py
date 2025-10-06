# app/repositories/save_docs_repo.py
from typing import Any, Dict, Optional, List, Tuple
from sqlalchemy import insert
from sqlalchemy.engine import Connection
from datetime import datetime, date
import re

from app.models import (
    invoice_docs, bank_statement_docs,
    passport_docs, visa_docs, work_permit_docs,
    resume_docs, injury_report_docs_docs,
)

# ------------------------
# helpers to read shaped dicts
# ------------------------
def _val(d: Dict[str, Any], key: str):
    """
    shaped["fields"][key] -> {"value": ..., "confidence": ...}
    return the .value (or None)
    """
    obj = d.get(key) or {}
    return obj.get("value")

_DATE_PATTERNS: List[Tuple[str, str]] = [
    (r"^\d{4}-\d{2}-\d{2}$", "%Y-%m-%d"),         # 2024-02-19
    (r"^\d{2}/\d{2}/\d{4}$", "%d/%m/%Y"),         # 19/02/2024
    (r"^\d{2}-\d{2}-\d{4}$", "%d-%m-%Y"),         # 19-02-2024
    (r"^\d{4}/\d{2}/\d{2}$", "%Y/%m/%d"),         # 2024/02/19
]

def _to_date(v: Any) -> Optional[date]:
    if v is None: 
        return None
    if isinstance(v, date):  # already a date
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, (int, float)):
        # rare; don’t guess numeric -> date
        return None
    s = str(v).strip()
    for rx, fmt in _DATE_PATTERNS:
        if re.match(rx, s):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                pass
    # last try: isoformat with time
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

def _to_text(v: Any) -> Optional[str]:
    if v is None:
        return None
    # If value is an address-like dict, stringify conservatively
    if isinstance(v, (dict, list)):
        return str(v)
    return str(v)

# ------------------------
# INSERT FUNCTIONS
# ------------------------

def save_invoice(conn: Connection, *, model_id: str,
                 source_filename: Optional[str], source_url: Optional[str],
                 content_type: Optional[str],
                 shaped: Dict[str, Any]) -> str:
    f = shaped.get("fields", {})
    stmt = insert(invoice_docs).values(
        model_id=model_id,
        source_filename=source_filename,
        source_url=source_url,
        content_type=content_type,

        vendor_name=_to_text(_val(f, "VendorName")),
        vendor_address=_to_text(_val(f, "VendorAddress")),
        vendor_address_recipient=_to_text(_val(f, "VendorAddressRecipient")),
        customer_name=_to_text(_val(f, "CustomerName")),
        customer_id=_to_text(_val(f, "CustomerId")),
        customer_address=_to_text(_val(f, "CustomerAddress")),
        customer_address_recipient=_to_text(_val(f, "CustomerAddressRecipient")),
        invoice_id=_to_text(_val(f, "InvoiceId")),
        invoice_date=_to_date(_val(f, "InvoiceDate")),
        invoice_total=_to_num(_val(f, "InvoiceTotal")),
        due_date=_to_date(_val(f, "DueDate")),
        purchase_order=_to_text(_val(f, "PurchaseOrder")),
        billing_address=_to_text(_val(f, "BillingAddress")),
        billing_address_recipient=_to_text(_val(f, "BillingAddressRecipient")),
        shipping_address=_to_text(_val(f, "ShippingAddress")),
        shipping_address_recipient=_to_text(_val(f, "ShippingAddressRecipient")),
        subtotal=_to_num(_val(f, "SubTotal")),
        total_tax=_to_num(_val(f, "TotalTax")),
        previous_unpaid_balance=_to_num(_val(f, "PreviousUnpaidBalance")),
        amount_due=_to_num(_val(f, "AmountDue")),
        service_start_date=_to_date(_val(f, "ServiceStartDate")),
        service_end_date=_to_date(_val(f, "ServiceEndDate")),
        service_address=_to_text(_val(f, "ServiceAddress")),
        service_address_recipient=_to_text(_val(f, "ServiceAddressRecipient")),
        remittance_address=_to_text(_val(f, "RemittanceAddress")),
        remittance_address_recipient=_to_text(_val(f, "RemittanceAddressRecipient")),

        fields=shaped.get("fields", {}),
        items=shaped.get("items"),
    ).returning(invoice_docs.c.id)
    return str(conn.execute(stmt).scalar_one())

def save_bank_statement(conn: Connection, *, model_id: str,
                        source_filename: Optional[str], source_url: Optional[str],
                        content_type: Optional[str],
                        shaped: Dict[str, Any]) -> str:
    f = shaped.get("fields", {})
    stmt = insert(bank_statement_docs).values(
        model_id=model_id,
        source_filename=source_filename,
        source_url=source_url,
        content_type=content_type,

        account_holder_name=_to_text(_val(f, "AccountHolderName")),
        account_holder_address=_to_text(_val(f, "AccountHolderAddress")),
        bank_name=_to_text(_val(f, "BankName")),
        bank_address=_to_text(_val(f, "BankAddress")),
        statement_start_date=_to_date(_val(f, "StatementStartDate")),
        statement_end_date=_to_date(_val(f, "StatementEndDate")),

        fields=shaped.get("fields", {}),
        accounts=shaped.get("accounts"),
    ).returning(bank_statement_docs.c.id)
    return str(conn.execute(stmt).scalar_one())

def save_passport(conn: Connection, *, model_id: str,
                  source_filename: Optional[str], source_url: Optional[str],
                  content_type: Optional[str],
                  shaped: Dict[str, Any]) -> str:
    f = shaped.get("fields", {})
    stmt = insert(passport_docs).values(
        model_id=model_id,
        source_filename=source_filename,
        source_url=source_url,
        content_type=content_type,

        document_type=_to_text(_val(f, "DocumentType")),
        country_region=_to_text(_val(f, "CountryRegion")),
        region=_to_text(_val(f, "Region")),
        first_name=_to_text(_val(f, "FirstName")),
        last_name=_to_text(_val(f, "LastName")),
        full_name=_to_text(_val(f, "FullName")),
        document_number=_to_text(_val(f, "DocumentNumber")),
        date_of_birth=_to_date(_val(f, "DateOfBirth")),
        date_of_issue=_to_date(_val(f, "DateOfIssue")),
        date_of_expiration=_to_date(_val(f, "DateOfExpiration")),
        sex=_to_text(_val(f, "Sex")),
        nationality=_to_text(_val(f, "Nationality")),
        address_text=_to_text(_val(f, "Address")),
        machine_readable_zone=_to_text(_val(f, "MachineReadableZone")),

        issuing_country=_to_text(_val(f, "IssuingCountry")),
        issuer=_to_text(_val(f, "Issuer")),
        place_of_birth=_to_text(_val(f, "PlaceOfBirth")),

        fields=shaped.get("fields", {}),
    ).returning(passport_docs.c.id)
    return str(conn.execute(stmt).scalar_one())

def save_visa(conn: Connection, *, model_id: str,
              source_filename: Optional[str], source_url: Optional[str],
              content_type: Optional[str],
              shaped: Dict[str, Any]) -> str:
    f = shaped.get("fields", {})
    stmt = insert(visa_docs).values(
        model_id=model_id,
        source_filename=source_filename,
        source_url=source_url,
        content_type=content_type,

        document_type=_to_text(_val(f, "DocumentType")),
        country_region=_to_text(_val(f, "CountryRegion")),
        region=_to_text(_val(f, "Region")),
        first_name=_to_text(_val(f, "FirstName")),
        last_name=_to_text(_val(f, "LastName")),
        full_name=_to_text(_val(f, "FullName")),
        document_number=_to_text(_val(f, "DocumentNumber")),
        date_of_birth=_to_date(_val(f, "DateOfBirth")),
        date_of_issue=_to_date(_val(f, "DateOfIssue")),
        date_of_expiration=_to_date(_val(f, "DateOfExpiration")),
        sex=_to_text(_val(f, "Sex")),
        nationality=_to_text(_val(f, "Nationality")),
        address_text=_to_text(_val(f, "Address")),
        machine_readable_zone=_to_text(_val(f, "MachineReadableZone")),

        visa_number=_to_text(_val(f, "VisaNumber")),
        visa_type=_to_text(_val(f, "VisaType")),
        entries=_to_text(_val(f, "Entries")),
        duration_of_stay=_to_text(_val(f, "DurationOfStay")),
        issuing_country=_to_text(_val(f, "IssuingCountry")),
        issuer=_to_text(_val(f, "Issuer")),

        fields=shaped.get("fields", {}),
    ).returning(visa_docs.c.id)
    return str(conn.execute(stmt).scalar_one())

def save_work_permit(conn: Connection, *, model_id: str,
                     source_filename: Optional[str], source_url: Optional[str],
                     content_type: Optional[str],
                     shaped: Dict[str, Any]) -> str:
    f = shaped.get("fields", {})
    stmt = insert(work_permit_docs).values(
        model_id=model_id,
        source_filename=source_filename,
        source_url=source_url,
        content_type=content_type,

        document_type=_to_text(_val(f, "DocumentType")),
        country_region=_to_text(_val(f, "CountryRegion")),
        region=_to_text(_val(f, "Region")),
        first_name=_to_text(_val(f, "FirstName")),
        last_name=_to_text(_val(f, "LastName")),
        full_name=_to_text(_val(f, "FullName")),
        document_number=_to_text(_val(f, "DocumentNumber")),
        date_of_birth=_to_date(_val(f, "DateOfBirth")),
        date_of_issue=_to_date(_val(f, "DateOfIssue")),
        date_of_expiration=_to_date(_val(f, "DateOfExpiration")),
        sex=_to_text(_val(f, "Sex")),
        nationality=_to_text(_val(f, "Nationality")),
        address_text=_to_text(_val(f, "Address")),
        machine_readable_zone=_to_text(_val(f, "MachineReadableZone")),

        permit_number=_to_text(_val(f, "PermitNumber")),
        permit_type=_to_text(_val(f, "PermitType")),
        employer=_to_text(_val(f, "Employer")),
        occupation=_to_text(_val(f, "Occupation")),
        issuing_country=_to_text(_val(f, "IssuingCountry")),
        issuer=_to_text(_val(f, "Issuer")),

        fields=shaped.get("fields", {}),
    ).returning(work_permit_docs.c.id)
    return str(conn.execute(stmt).scalar_one())

def save_resume(conn: Connection, *, model_id: str,
                source_filename: Optional[str], source_url: Optional[str],
                content_type: Optional[str],
                shaped: Dict[str, Any]) -> str:
    stmt = insert(resume_docs).values(
        model_id=model_id,
        source_filename=source_filename,
        source_url=source_url,
        content_type=content_type,

        doc_inferred_type=shaped.get("doc_type"),
        fields=shaped.get("fields", {}),
    ).returning(resume_docs.c.id)
    return str(conn.execute(stmt).scalar_one())

def save_injury_report(conn: Connection, *, model_id: str,
                       source_filename: Optional[str], source_url: Optional[str],
                       content_type: Optional[str],
                       shaped: Dict[str, Any]) -> str:
    stmt = insert(injury_report_docs_docs).values(
        model_id=model_id,
        source_filename=source_filename,
        source_url=source_url,
        content_type=content_type,

        doc_inferred_type=shaped.get("doc_type"),
        fields=shaped.get("fields", {}),
    ).returning(injury_report_docs_docs.c.id)
    return str(conn.execute(stmt).scalar_one())
