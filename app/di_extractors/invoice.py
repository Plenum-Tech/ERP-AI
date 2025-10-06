"""
Invoice extractor using Azure AI Document Intelligence (v4).
- analyze_invoice_url() / analyze_invoice_bytes() -> AnalyzeResult
- invoice_to_dict() -> dict with fields/items (value + confidence)
- print_invoice() -> console output similar to MS sample

Env:
  AZ_DI_ENDPOINT_PRIMARY (or AZ_DI_ENDPOINT)
  AZ_DI_KEY
"""

import os
from typing import Any, Dict, Optional, Iterable, List
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

load_dotenv()

ENDPOINT = os.getenv("AZ_DI_ENDPOINT_PRIMARY") or os.getenv("AZ_DI_ENDPOINT") or "https://erpdocintelligence.cognitiveservices.azure.com/"
KEY      = os.getenv("AZ_DI_KEY", "6J510LpGX7uJgC22e6nzazFrwN1uf59dBT9q4XwqZzAeHBIfm5OpJQQJ99BIACYeBjFXJ3w3AAALACOGOE5h")

MODEL_ID = "prebuilt-invoice"

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
def analyze_invoice_url(form_url: str):
    c = _client()
    try:
        return c.begin_analyze_document(MODEL_ID, AnalyzeDocumentRequest(url_source=form_url)).result()
    except ResourceNotFoundError as e:
        raise RuntimeError(
            f"404 from Document Intelligence. Check endpoint/key and model '{MODEL_ID}' availability."
        ) from e

def analyze_invoice_bytes(content: bytes, content_type: Optional[str] = None):
    if not content:
        raise ValueError("Uploaded file is empty.")
    c = _client()
    try:
        # For bytes, pass raw content + content_type (no AnalyzeDocumentRequest)
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
# Safe access helpers
# -----------------------------
def _kv(value_obj: Any) -> Dict[str, Any]:
    """
    Return {'value': <typed>, 'confidence': <float>} handling both v4 and older-style accessors.
    """
    if value_obj is None:
        return {"value": None, "confidence": None}

    # confidence
    conf = getattr(value_obj, "confidence", None)

    # try v4 "value"
    val = getattr(value_obj, "value", None)

    # legacy convenience props
    if val is None:
        for attr in ("value_string", "value_number", "value_address", "value_date", "value_time", "value_country_region"):
            if hasattr(value_obj, attr):
                val = getattr(value_obj, attr)
                break

    # currency handling
    if val is None and hasattr(value_obj, "value_currency"):
        cur = getattr(value_obj, "value_currency", None)
        if cur is not None and hasattr(cur, "amount"):
            val = cur.amount
        else:
            val = cur

    # if still none, fall back to plain content (string)
    if val is None and hasattr(value_obj, "content"):
        val = getattr(value_obj, "content")

    # unwrap currency-like object with .amount
    if hasattr(val, "amount"):
        val = getattr(val, "amount", val)

    return {"value": val, "confidence": conf}

def _get_items_array(items_field: Any) -> Iterable[Any]:
    """Return iterable of items for either .value (v4) or .value_array (older samples)."""
    if items_field is None:
        return []
    arr = getattr(items_field, "value", None)
    if isinstance(arr, list):
        return arr
    arr = getattr(items_field, "value_array", None)
    if isinstance(arr, list):
        return arr
    return []

def _get_props(item_field: Any) -> Dict[str, Any]:
    """Return dict-like props for either .properties (v4) or .value_object (older samples)."""
    if item_field is None:
        return {}
    props = getattr(item_field, "properties", None)
    if isinstance(props, dict):
        return props
    props = getattr(item_field, "value_object", None)
    if isinstance(props, dict):
        return props
    return {}

def _print_kv(label: str, obj: Any):
    k = _kv(obj)
    if k["value"] is not None:
        print(f"{label}: {k['value']} has confidence: {k['confidence']}")

# -----------------------------
# Shaping / Printing
# -----------------------------
def invoice_to_dict(result) -> Dict[str, Any]:
    """
    Geometry-free JSON for invoices:
    {
      "fields": { <name>: {"value": ..., "confidence": ...}, ... },
      "items":  [ { "Description": {...}, "Quantity": {...}, ... }, ... ]
    }
    """
    out: Dict[str, Any] = {"fields": {}, "items": []}
    if not result or not result.documents:
        return out

    f = result.documents[0].fields

    # Top-level fields (aligned to your sample)
    names = [
        "VendorName","VendorAddress","VendorAddressRecipient",
        "CustomerName","CustomerId","CustomerAddress","CustomerAddressRecipient",
        "InvoiceId","InvoiceDate","InvoiceTotal","DueDate",
        "PurchaseOrder","BillingAddress","BillingAddressRecipient",
        "ShippingAddress","ShippingAddressRecipient",
        "SubTotal","TotalTax","PreviousUnpaidBalance","AmountDue",
        "ServiceStartDate","ServiceEndDate","ServiceAddress","ServiceAddressRecipient",
        "RemittanceAddress","RemittanceAddressRecipient",
    ]
    out["fields"] = {name: _kv(f.get(name)) for name in names}

    # Line items (handle both shapes)
    items_field = f.get("Items")
    for it in _get_items_array(items_field):
        props = _get_props(it)
        out["items"].append({
            "Description": _kv(props.get("Description")),
            "Quantity":    _kv(props.get("Quantity")),
            "Unit":        _kv(props.get("Unit")),
            "UnitPrice":   _kv(props.get("UnitPrice")),
            "ProductCode": _kv(props.get("ProductCode")),
            "Date":        _kv(props.get("Date")),
            "Tax":         _kv(props.get("Tax")),
            "Amount":      _kv(props.get("Amount")),
        })

    return out

def print_invoice(result) -> None:
    """Console output that mirrors the MS sample (value + confidence)."""
    if not result or not result.documents:
        print("No invoice detected.")
        return

    inv = result.documents[0]
    f = inv.fields

    print("--------Recognizing invoice--------")
    # top-level fields
    for name, data in invoice_to_dict(result)["fields"].items():
        if data["value"] is not None:
            print(f"{name}: {data['value']} has confidence: {data['confidence']}")

    # items (handle both shapes)
    items_field = f.get("Items")
    items = list(_get_items_array(items_field))
    if items:
        print("Invoice items:")
        for idx, it in enumerate(items):
            print(f"...Item #{idx + 1}")
            props = _get_props(it)
            for label in ["Description","Quantity","Unit","UnitPrice","ProductCode","Date","Tax","Amount"]:
                _print_kv(f"......{label}", props.get(label))

    print("----------------------------------------")

# -----------------------------
# CLI quick test
# -----------------------------
if __name__ == "__main__":
    sample_url = "https://raw.githubusercontent.com/Azure-Samples/cognitive-services-REST-api-samples/master/curl/form-recognizer/invoice_sample.jpg"
    result = analyze_invoice_url(sample_url)
    print_invoice(result)
