"""
Receipt extractor using Azure AI Document Intelligence (v4).

- analyze_receipt_url() / analyze_receipt_bytes() -> AnalyzeResult
- receipt_to_dict() -> dict with fields/items (value + confidence)
- print_receipt() -> console output similar to the MS sample

Env:
  AZ_DI_ENDPOINT_PRIMARY (or AZ_DI_ENDPOINT)
  AZ_DI_KEY
"""

import os
from typing import Any, Dict, List, Optional, Iterable
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

load_dotenv()

ENDPOINT = os.getenv("AZ_DI_ENDPOINT_PRIMARY") or os.getenv("AZ_DI_ENDPOINT") or "https://erpdocintelligence.cognitiveservices.azure.com/"
KEY      = os.getenv("AZ_DI_KEY", "6J510LpGX7uJgC22e6nzazFrwN1uf59dBT9q4XwqZzAeHBIfm5OpJQQJ99BIACYeBjFXJ3w3AAALACOGOE5h")

MODEL_ID = "prebuilt-receipt"

# -----------------------------
# Client helpers
# -----------------------------
def _client() -> DocumentIntelligenceClient:
    if not ENDPOINT or not KEY:
        raise RuntimeError("Set AZ_DI_ENDPOINT_PRIMARY (or AZ_DI_ENDPOINT) and AZ_DI_KEY in your environment/.env")
    return DocumentIntelligenceClient(endpoint=ENDPOINT, credential=AzureKeyCredential(KEY))

# -----------------------------
# Analyze helpers
# -----------------------------
def analyze_receipt_url(doc_url: str):
    c = _client()
    try:
        return c.begin_analyze_document(MODEL_ID, AnalyzeDocumentRequest(url_source=doc_url)).result()
    except ResourceNotFoundError as e:
        raise RuntimeError(
            f"404 from Document Intelligence. Check endpoint/key and model '{MODEL_ID}' availability."
        ) from e

def analyze_receipt_bytes(content: bytes, content_type: Optional[str] = None):
    if not content:
        raise ValueError("Uploaded file is empty.")
    c = _client()
    try:
        # RAW BYTES + content_type (no AnalyzeDocumentRequest)
        return c.begin_analyze_document(
            MODEL_ID,
            content,
            content_type=content_type or "application/octet-stream",
        ).result()
    except ResourceNotFoundError as e:
        raise RuntimeError(
            f"404 from Document Intelligence. Check endpoint/key and model '{MODEL_ID}' availability."
        ) from e
    except HttpResponseError as e:
        raise RuntimeError(f"DI analyze failed: {e.message}") from e

# -----------------------------
# Value + shape helpers (v4 + legacy-safe)
# -----------------------------
def _kv(value_obj: Any) -> Dict[str, Any]:
    """Return {'value': <typed>, 'confidence': <float>} handling v4 and legacy accessors."""
    if value_obj is None:
        return {"value": None, "confidence": None}

    conf = getattr(value_obj, "confidence", None)

    # v4 primary
    val = getattr(value_obj, "value", None)

    # legacy convenience props
    if val is None:
        for attr in ("value_string", "value_number", "value_date", "value_time", "value_address"):
            if hasattr(value_obj, attr):
                val = getattr(value_obj, attr)
                break

    # currency handling (value_currency)
    if val is None and hasattr(value_obj, "value_currency"):
        cur = getattr(value_obj, "value_currency", None)
        if cur is not None and hasattr(cur, "amount"):
            val = cur.amount
        else:
            val = cur

    # final fallback to raw text
    if val is None and hasattr(value_obj, "content"):
        val = getattr(value_obj, "content")

    # unwrap any currency-like .amount
    if hasattr(val, "amount"):
        val = getattr(val, "amount", val)

    return {"value": val, "confidence": conf}

def _get_array(field: Any) -> Iterable[Any]:
    """Return iterable from .value (v4) or .value_array (legacy)."""
    if field is None:
        return []
    arr = getattr(field, "value", None)
    if isinstance(arr, list):
        return arr
    arr = getattr(field, "value_array", None)
    if isinstance(arr, list):
        return arr
    return []

def _get_props(field: Any) -> Dict[str, Any]:
    """Return dict-like props from .properties (v4) or .value_object (legacy)."""
    if field is None:
        return {}
    props = getattr(field, "properties", None)
    if isinstance(props, dict):
        return props
    props = getattr(field, "value_object", None)
    if isinstance(props, dict):
        return props
    return {}

def _print_kv(label: str, obj: Any):
    k = _kv(obj)
    if k["value"] is not None:
        print(f"{label}: {k['value']} has confidence: {k['confidence']}")

# -----------------------------
# Shaping
# -----------------------------
# core header fields commonly returned by prebuilt-receipt
_HEADER_FIELDS: List[str] = [
    "MerchantName",
    "MerchantPhoneNumber",
    "MerchantAddress",
    "MerchantAddressRecipient",
    "TransactionDate",
    "TransactionTime",
    "Total",
    "Subtotal",
    "TotalTax",
    "Tip",
    "Currency",
    "PaymentMethod",
    "CardNumber",
    "ReceiptType",     # sometimes also exposed via document.doc_type
    "CustomerName",
    "OrderNumber",
    "InvoiceId",
]

# per-item fields inside Items[]
_ITEM_FIELDS: List[str] = ["Description", "Quantity", "Price", "TotalPrice", "ProductCode", "Date", "Category"]

def receipt_to_dict(result) -> Dict[str, Any]:
    """
    Geometry-free JSON:
    {
      "doc_type": <document.doc_type>,
      "fields": { <name>: {"value": ..., "confidence": ...}, ... },
      "items":  [ { "Description": {...}, "Quantity": {...}, ... }, ... ]
    }
    """
    out: Dict[str, Any] = {"doc_type": None, "fields": {}, "items": []}
    if not result or not result.documents:
        return out

    doc = result.documents[0]
    f   = doc.fields
    out["doc_type"] = getattr(doc, "doc_type", None)

    # header fields
    for name in _HEADER_FIELDS:
        if name in f:
            out["fields"][name] = _kv(f.get(name))

    # items (robust to v4/legacy)
    items = f.get("Items")
    for it in _get_array(items):
        props = _get_props(it)
        out["items"].append({k: _kv(props.get(k)) for k in _ITEM_FIELDS})

    return out

# -----------------------------
# Printing (sample-like)
# -----------------------------
def print_receipt(result) -> None:
    if not result or not result.documents:
        print("No receipt detected.")
        return

    doc = result.documents[0]
    f   = doc.fields
    print("--------Recognizing receipt--------")

    # doc type (if present on document)
    if getattr(doc, "doc_type", None):
        print(f"Receipt Type: {doc.doc_type}")

    # header fields
    shaped = receipt_to_dict(result)
    for k, v in shaped["fields"].items():
        if v["value"] is not None:
            print(f"{k}: {v['value']} has confidence: {v['confidence']}")

    # items
    items = f.get("Items")
    rows = list(_get_array(items))
    if rows:
        print("Receipt items:")
        for idx, it in enumerate(rows):
            print(f"...Item #{idx + 1}")
            props = _get_props(it)
            for name in _ITEM_FIELDS:
                _print_kv(f"......{name}", props.get(name))

    print("--------------------------------------")

# -----------------------------
# CLI quick test
# -----------------------------
if __name__ == "__main__":
    # Microsoft sample receipt
    sample_url = "https://raw.githubusercontent.com/Azure/azure-sdk-for-python/main/sdk/formrecognizer/azure-ai-formrecognizer/tests/sample_forms/receipt/contoso-receipt.png"
    res = analyze_receipt_url(sample_url)
    print_receipt(res)
