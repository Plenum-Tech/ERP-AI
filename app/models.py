# app/models.py
from sqlalchemy import (
    MetaData, Table, Column, String, Date, Time, Numeric, DateTime, text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid

# correct schema
metadata = MetaData(schema="erp_ai")

# helpers
def uuid_pk():
    return Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

def common_meta():
    return [
        Column("model_id", String, nullable=False),       # e.g., prebuilt-invoice, prebuilt-idDocument
        Column("source_filename", String),
        Column("source_url", String),
        Column("content_type", String),
        Column("created_at", DateTime(timezone=True), server_default=text("now()")),
    ]

# -----------------------------------------------------------
# INVOICE  (from invoice.invoice_to_dict: fields + items[])
# -----------------------------------------------------------
invoice_docs = Table(
    "invoice_docs",
    metadata,
    uuid_pk(),
    *common_meta(),
    # flattened key invoice fields
    Column("vendor_name", String),
    Column("vendor_address", String),
    Column("vendor_address_recipient", String),
    Column("customer_name", String),
    Column("customer_id", String),
    Column("customer_address", String),
    Column("customer_address_recipient", String),
    Column("invoice_id", String),
    Column("invoice_date", Date),
    Column("invoice_total", Numeric),
    Column("due_date", Date),
    Column("purchase_order", String),
    Column("billing_address", String),
    Column("billing_address_recipient", String),
    Column("shipping_address", String),
    Column("shipping_address_recipient", String),
    Column("subtotal", Numeric),
    Column("total_tax", Numeric),
    Column("previous_unpaid_balance", Numeric),
    Column("amount_due", Numeric),
    Column("service_start_date", Date),
    Column("service_end_date", Date),
    Column("service_address", String),
    Column("service_address_recipient", String),
    Column("remittance_address", String),
    Column("remittance_address_recipient", String),
    # full shaped payloads
    Column("fields", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("items", JSONB),  # array of line items: Description, Quantity, Unit, UnitPrice, ProductCode, Date, Tax, Amount
)

# -----------------------------------------------------------
# BANK STATEMENT (from bank_statement.bank_stmt_to_dict: fields + accounts[])
# -----------------------------------------------------------
bank_statement_docs = Table(
    "bank_statement_docs",
    metadata,
    uuid_pk(),
    *common_meta(),
    # header fields
    Column("account_holder_name", String),
    Column("account_holder_address", String),
    Column("bank_name", String),
    Column("bank_address", String),
    Column("statement_start_date", Date),
    Column("statement_end_date", Date),
    # full shaped payloads
    Column("fields", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("accounts", JSONB),  # list of accounts, each with balances and Transactions[]
)

# -----------------------------------------------------------
# PASSPORT (ID doc; from id_document.id_to_dict: fields)
# -----------------------------------------------------------
passport_docs = Table(
    "passport_docs",
    metadata,
    uuid_pk(),
    *common_meta(),
    # common ID fields
    Column("document_type", String),
    Column("country_region", String),
    Column("region", String),
    Column("first_name", String),
    Column("last_name", String),
    Column("full_name", String),
    Column("document_number", String),
    Column("date_of_birth", Date),
    Column("date_of_issue", Date),
    Column("date_of_expiration", Date),
    Column("sex", String),
    Column("nationality", String),
    Column("address_text", String),
    Column("machine_readable_zone", String),
    # passport-specific extras
    Column("issuing_country", String),
    Column("issuer", String),
    Column("place_of_birth", String),
    # full shaped payload
    Column("fields", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
)

# -----------------------------------------------------------
# VISA (ID doc; from id_document.id_to_dict: fields)
# -----------------------------------------------------------
visa_docs = Table(
    "visa_docs",
    metadata,
    uuid_pk(),
    *common_meta(),
    # common ID fields
    Column("document_type", String),
    Column("country_region", String),
    Column("region", String),
    Column("first_name", String),
    Column("last_name", String),
    Column("full_name", String),
    Column("document_number", String),
    Column("date_of_birth", Date),
    Column("date_of_issue", Date),
    Column("date_of_expiration", Date),
    Column("sex", String),
    Column("nationality", String),
    Column("address_text", String),
    Column("machine_readable_zone", String),
    # visa-specific extras
    Column("visa_number", String),
    Column("visa_type", String),
    Column("entries", String),
    Column("duration_of_stay", String),
    Column("issuing_country", String),
    Column("issuer", String),
    # full shaped payload
    Column("fields", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
)

# -----------------------------------------------------------
# WORK PERMIT (ID doc; from id_document.id_to_dict: fields)
# -----------------------------------------------------------
work_permit_docs = Table(
    "work_permit_docs",
    metadata,
    uuid_pk(),
    *common_meta(),
    # common ID fields
    Column("document_type", String),
    Column("country_region", String),
    Column("region", String),
    Column("first_name", String),
    Column("last_name", String),
    Column("full_name", String),
    Column("document_number", String),
    Column("date_of_birth", Date),
    Column("date_of_issue", Date),
    Column("date_of_expiration", Date),
    Column("sex", String),
    Column("nationality", String),
    Column("address_text", String),
    Column("machine_readable_zone", String),
    # permit-specific extras
    Column("permit_number", String),
    Column("permit_type", String),
    Column("employer", String),
    Column("occupation", String),
    Column("issuing_country", String),
    Column("issuer", String),
    # full shaped payload
    Column("fields", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
)

# -----------------------------------------------------------
# RESUME (generic doc; from generic_document.generic_to_dict: doc_type + fields)
# -----------------------------------------------------------
resume_docs = Table(
    "resume_docs",
    metadata,
    uuid_pk(),
    *common_meta(),
    Column("doc_inferred_type", String),  # from result.documents[0].doc_type (generic model)
    Column("fields", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
)

# -----------------------------------------------------------
# INJURY REPORT (generic doc; from generic_document.generic_to_dict: doc_type + fields)
# table name matches your list literally: injury_report_docs_docs
# -----------------------------------------------------------
injury_report_docs_docs = Table(
    "injury_report_docs_docs",
    metadata,
    uuid_pk(),
    *common_meta(),
    Column("doc_inferred_type", String),
    Column("fields", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
)
