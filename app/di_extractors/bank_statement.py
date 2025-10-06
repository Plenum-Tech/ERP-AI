"""
Bank Statement extractor using Azure AI Document Intelligence (v4).

- analyze_bank_stmt_url() / analyze_bank_stmt_bytes() -> AnalyzeResult
- bank_stmt_to_dict() -> dict with fields/accounts/transactions (value + confidence)
- print_bank_stmt() -> console output similar to the MS sample

Env:
  AZ_DI_ENDPOINT_PRIMARY (or AZ_DI_ENDPOINT)
  AZ_DI_KEY
  MODEL_BANKSTMT                (default: prebuilt-bankStatement.us)
  ALLOW_DEGRADED_FALLBACK=true  (optional)
  MODEL_BANKSTMT_FALLBACK       (default: prebuilt-document)
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

MODEL_ID                = os.getenv("MODEL_BANKSTMT", "prebuilt-bankStatement.us")
ALLOW_DEGRADED_FALLBACK = os.getenv("ALLOW_DEGRADED_FALLBACK", "true").lower() == "true"
MODEL_ID_FALLBACK       = os.getenv("MODEL_BANKSTMT_FALLBACK", "prebuilt-document")

# -----------------------------
# Client helpers
# -----------------------------
def _client() -> DocumentIntelligenceClient:
    if not ENDPOINT or not KEY:
        raise RuntimeError("Set AZ_DI_ENDPOINT_PRIMARY (or AZ_DI_ENDPOINT) and AZ_DI_KEY in your environment/.env")
    return DocumentIntelligenceClient(endpoint=ENDPOINT, credential=AzureKeyCredential(KEY))

# -----------------------------
# Analyze helpers (URL / bytes with optional degraded fallback)
# -----------------------------
def _analyze_url(model_id: str, url: str):
    c = _client()
    return c.begin_analyze_document(model_id, AnalyzeDocumentRequest(url_source=url)).result()

def _analyze_bytes(model_id: str, content: bytes, content_type: Optional[str]):
    c = _client()
    return c.begin_analyze_document(model_id, content, content_type=content_type or "application/octet-stream").result()

def analyze_bank_stmt_url(doc_url: str):
    try:
        return _analyze_url(MODEL_ID, doc_url)
    except (ResourceNotFoundError, HttpResponseError) as e:
        # 404 or model-not-found wording -> optional fallback
        if ALLOW_DEGRADED_FALLBACK and (getattr(e, "status_code", None) == 404 or "model" in (getattr(e, "message", "") or "").lower()):
            return _analyze_url(MODEL_ID_FALLBACK, doc_url)
        raise

def analyze_bank_stmt_bytes(content: bytes, content_type: Optional[str] = None):
    if not content:
        raise ValueError("Uploaded file is empty.")
    try:
        return _analyze_bytes(MODEL_ID, content, content_type)
    except (ResourceNotFoundError, HttpResponseError) as e:
        if ALLOW_DEGRADED_FALLBACK and (getattr(e, "status_code", None) == 404 or "model" in (getattr(e, "message", "") or "").lower()):
            return _analyze_bytes(MODEL_ID_FALLBACK, content, content_type)
        raise

# -----------------------------
# Safe value helpers (v4 + legacy)
# -----------------------------
def _kv(value_obj: Any) -> Dict[str, Any]:
    """Return {'value': <typed>, 'confidence': <float>} handling v4 and legacy accessors."""
    if value_obj is None:
        return {"value": None, "confidence": None}

    conf = getattr(value_obj, "confidence", None)

    # v4 preferred
    val = getattr(value_obj, "value", None)

    # legacy convenience props
    if val is None:
        for attr in ("value_number", "value_string", "value_date", "value_time", "value_address"):
            if hasattr(value_obj, attr):
                val = getattr(value_obj, attr)
                break

    # currency handling (legacy/value_currency)
    if val is None and hasattr(value_obj, "value_currency"):
        cur = getattr(value_obj, "value_currency", None)
        if cur is not None and hasattr(cur, "amount"):
            val = cur.amount
        else:
            val = cur

    # final fallback to content
    if val is None and hasattr(value_obj, "content"):
        val = getattr(value_obj, "content")

    # unwrap currency-like objects that still have .amount
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
def bank_stmt_to_dict(result) -> Dict[str, Any]:
    """
    Geometry-free JSON:
    {
      "fields": { <name>: {"value": ..., "confidence": ...}, ... },
      "accounts": [
        {
          "AccountNumber": {...},
          "AccountType": {...},
          "BeginningBalance": {...},
          "EndingBalance": {...},
          "TotalServiceFees": {...},
          "Transactions": [
            {"Date": {...}, "Description": {...}, "DepositAmount": {...}, "WithdrawalAmount": {...}}
          ]
        }
      ]
    }
    """
    out: Dict[str, Any] = {"fields": {}, "accounts": []}
    if not result or not result.documents:
        return out

    doc = result.documents[0]
    f   = doc.fields

    # Header-level fields
    top_names = [
        "AccountHolderName", "AccountHolderAddress",
        "BankName", "BankAddress",
        "StatementStartDate", "StatementEndDate",
    ]
    out["fields"] = {name: _kv(f.get(name)) for name in top_names}

    # Accounts (array, robust to v4/legacy)
    accounts = f.get("Accounts")
    for acc in _get_array(accounts):
        props = _get_props(acc)
        rec: Dict[str, Any] = {
            "AccountNumber":     _kv(props.get("AccountNumber")),
            "AccountType":       _kv(props.get("AccountType")),
            "BeginningBalance":  _kv(props.get("BeginningBalance")),
            "EndingBalance":     _kv(props.get("EndingBalance")),
            "TotalServiceFees":  _kv(props.get("TotalServiceFees")),
            "Transactions":      [],
        }

        txs = props.get("Transactions")
        for t in _get_array(txs):
            tprops = _get_props(t)
            rec["Transactions"].append({
                "Date":              _kv(tprops.get("Date")),
                "Description":       _kv(tprops.get("Description")),
                "DepositAmount":     _kv(tprops.get("DepositAmount")),
                "WithdrawalAmount":  _kv(tprops.get("WithdrawalAmount")),
            })

        out["accounts"].append(rec)

    return out

# -----------------------------
# Printing (sample-like)
# -----------------------------
def print_bank_stmt(result) -> None:
    if not result or not result.documents:
        print("No bank statement detected.")
        return

    d = bank_stmt_to_dict(result)
    print("--------Recognizing statement--------")
    # header fields
    for k, v in d["fields"].items():
        if v["value"] is not None:
            print(f"{k}: {v['value']} has confidence: {v['confidence']}")

    # accounts + transactions
    for i, acc in enumerate(d["accounts"]):
        print(f"...Account #{i + 1}")
        for name in ["AccountNumber","AccountType","BeginningBalance","EndingBalance","TotalServiceFees"]:
            v = acc.get(name, {"value": None})
            if v and v["value"] is not None:
                print(f"......{name}: {v['value']} has confidence: {v.get('confidence')}")
        if acc.get("Transactions"):
            print("......Transactions:")
            for j, t in enumerate(acc["Transactions"]):
                print(f".........Transaction #{j + 1}")
                for tn in ["Date","Description","DepositAmount","WithdrawalAmount"]:
                    tv = t.get(tn, {"value": None})
                    if tv and tv["value"] is not None:
                        print(f"............{tn}: {tv['value']} has confidence: {tv.get('confidence')}")
    print("--------------------------------------")

# -----------------------------
# CLI quick test
# -----------------------------
if __name__ == "__main__":
    # Example:
    # with open("YOUR_FILE_PATH.pdf", "rb") as f:
    #     res = analyze_bank_stmt_bytes(f.read(), content_type="application/pdf")
    #     print_bank_stmt(res)
    pass
