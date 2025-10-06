"""
ID Document extractor (passport / visa / work_permit) using Azure AI Document Intelligence (v4).
- analyze_id_url() / analyze_id_bytes() -> AnalyzeResult
- id_to_dict(doc_kind=None) -> dict of fields (value + confidence)
- print_id(...) -> console output similar to the MS sample

Env:
  AZ_DI_ENDPOINT_PRIMARY (or AZ_DI_ENDPOINT)
  AZ_DI_KEY
"""

import os
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

load_dotenv()

ENDPOINT = os.getenv("AZ_DI_ENDPOINT_PRIMARY") or os.getenv("AZ_DI_ENDPOINT") or "https://erpdocintelligence.cognitiveservices.azure.com/"
KEY      = os.getenv("AZ_DI_KEY", "6J510LpGX7uJgC22e6nzazFrwN1uf59dBT9q4XwqZzAeHBIfm5OpJQQJ99BIACYeBjFXJ3w3AAALACOGOE5h")

MODEL_ID = "prebuilt-idDocument"

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
def analyze_id_url(doc_url: str):
    c = _client()
    try:
        return c.begin_analyze_document(MODEL_ID, AnalyzeDocumentRequest(url_source=doc_url)).result()
    except ResourceNotFoundError as e:
        raise RuntimeError(
            f"404 from Document Intelligence. Check endpoint/key and model '{MODEL_ID}' availability."
        ) from e

def analyze_id_bytes(content: bytes, content_type: Optional[str] = None):
    if not content:
        raise ValueError("Uploaded file is empty.")
    c = _client()
    try:
        # RAW BYTES + content_type (DO NOT wrap in AnalyzeDocumentRequest)
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
# Value helpers (v4 + legacy-safe)
# -----------------------------
def _kv(value_obj: Any) -> Dict[str, Any]:
    """
    Return {'value': <typed>, 'confidence': <float>} handling v4 and legacy accessors.
    Addresses/objects may be dict-like; we pass through as-is.
    """
    if value_obj is None:
        return {"value": None, "confidence": None}

    conf = getattr(value_obj, "confidence", None)

    # v4 primary
    val = getattr(value_obj, "value", None)

    # legacy convenience props
    if val is None:
        for attr in (
            "value_string", "value_number", "value_date", "value_time",
            "value_address", "value_country_region"
        ):
            if hasattr(value_obj, attr):
                val = getattr(value_obj, attr)
                break

    # currency (not typical for IDs, but harmless)
    if val is None and hasattr(value_obj, "value_currency"):
        cur = getattr(value_obj, "value_currency", None)
        if cur is not None and hasattr(cur, "amount"):
            val = cur.amount
        else:
            val = cur

    # final fallback to plain content
    if val is None and hasattr(value_obj, "content"):
        val = getattr(value_obj, "content")

    # unwrap currency-like objects if still present
    if hasattr(val, "amount"):
        val = getattr(val, "amount", val)

    return {"value": val, "confidence": conf}

def _has_value(value_obj: Any) -> bool:
    """Check if a field actually carries a value (v4 or legacy)."""
    if value_obj is None:
        return False
    if getattr(value_obj, "value", None) not in (None,):
        return True
    for attr in (
        "value_string", "value_number", "value_date", "value_time",
        "value_address", "value_country_region", "content", "value_currency"
    ):
        if getattr(value_obj, attr, None) not in (None,):
            return True
    return False

def _print_kv(label: str, obj: Any):
    k = _kv(obj)
    if k["value"] is not None:
        print(f"{label}: {k['value']} has confidence: {k['confidence']}")

# -----------------------------
# Field sets per doc kind
# -----------------------------
COMMON_PRIMARY = [
    "DocumentType", "CountryRegion", "Region",
    "FirstName", "LastName", "FullName",
    "DocumentNumber",
    "DateOfBirth", "DateOfIssue", "DateOfExpiration",
    "Sex", "Nationality",
    "Address",
    "MachineReadableZone",
]

PASSPORT_EXTRA = [
    "IssuingCountry", "Issuer", "PlaceOfBirth",
]

VISA_EXTRA = [
    "VisaNumber", "VisaType", "Entries", "DurationOfStay",
    "IssuingCountry", "Issuer",
]

WORK_PERMIT_EXTRA = [
    "PermitNumber", "PermitType", "Employer", "Occupation",
    "IssuingCountry", "Issuer",
]

def _keys_for_kind(doc_kind: Optional[str]) -> List[str]:
    doc_kind = (doc_kind or "").lower()
    base = list(COMMON_PRIMARY)
    if doc_kind == "passport":
        base += PASSPORT_EXTRA
    elif doc_kind == "visa":
        base += VISA_EXTRA
    elif doc_kind in ("work_permit", "work-permit", "workpermit", "residence_permit"):
        base += WORK_PERMIT_EXTRA
    return base

# -----------------------------
# Shaping / Printing
# -----------------------------
def id_to_dict(result, *, doc_kind: Optional[str] = None) -> Dict[str, Any]:
    """
    Geometry-free JSON for ID documents:
    {
      "fields": { <name>: {"value": ..., "confidence": ...}, ... }
    }
    Only includes keys the model actually returned (value != None).
    """
    out: Dict[str, Any] = {"fields": {}}
    if not result or not result.documents:
        return out

    d = result.documents[0]
    f = d.fields
    keys = _keys_for_kind(doc_kind)

    # Requested keys first
    for name in keys:
        val = f.get(name)
        if _has_value(val):
            out["fields"][name] = _kv(val)

    # Include any additional returned fields (future-proof)
    for k, v in f.items():
        if k not in out["fields"] and _has_value(v):
            out["fields"][k] = _kv(v)

    return out

def print_id(result, *, doc_kind: Optional[str] = None) -> None:
    """Console output similar to the MS sample (value + confidence)."""
    if not result or not result.documents:
        print("No ID document detected.")
        return

    print("--------Recognizing ID document--------")
    data = id_to_dict(result, doc_kind=doc_kind)
    for k, v in data["fields"].items():
        print(f"{k}: {v['value']} has confidence: {v['confidence']}")
    print("----------------------------------------")

# -----------------------------
# CLI quick test
# -----------------------------
if __name__ == "__main__":
    # Example sample URL (MS driver license sample)
    sample_url = "https://raw.githubusercontent.com/Azure-Samples/cognitive-services-REST-api-samples/master/curl/form-recognizer/DriverLicense.png"
    res = analyze_id_url(sample_url)
    print_id(res, doc_kind="passport")  # or "visa" / "work_permit"
