"""
Generic document extractor using Azure AI Document Intelligence (v4).

This version uses the prebuilt-layout model ONLY and enables native Key-Value Pair
extraction via the "features=keyValuePairs" flag. If the service still returns no
key_value_pairs, it DERIVES key-value pairs generically from page lines (no schema).

ENV:
  AZ_DI_ENDPOINT=https://<your-resource>.cognitiveservices.azure.com/
  AZ_DI_KEY=<your_document_intelligence_key>
"""

import os
import re
import mimetypes
from typing import Any, Dict, Optional, List
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

load_dotenv()

ENDPOINT = os.getenv("AZ_DI_ENDPOINT", "https://erpdocintelligence.cognitiveservices.azure.com/")
KEY      = os.getenv("AZ_DI_KEY","6J510LpGX7uJgC22e6nzazFrwN1uf59dBT9q4XwqZzAeHBIfm5OpJQQJ99BIACYeBjFXJ3w3AAALACOGOE5h")  # do NOT hardcode secrets

MODEL_ID = "prebuilt-layout"

# Try enum first; fall back to string for older SDKs
try:
    from azure.ai.documentintelligence.models import DocumentAnalysisFeature
    _KVP_FEATURES = [DocumentAnalysisFeature.KEY_VALUE_PAIRS]
except Exception:
    _KVP_FEATURES = ["keyValuePairs"]


def _client() -> DocumentIntelligenceClient:
    if not ENDPOINT or not KEY:
        raise RuntimeError("Set AZ_DI_ENDPOINT and AZ_DI_KEY in your environment/.env")
    return DocumentIntelligenceClient(endpoint=ENDPOINT, credential=AzureKeyCredential(KEY))


def _analyze(*, url: Optional[str] = None, content: Optional[bytes] = None, content_type: Optional[str] = None):
    """
    Always request KVPs from the prebuilt-layout model.
    """
    c = _client()
    if url:
        poller = c.begin_analyze_document(
            MODEL_ID,
            AnalyzeDocumentRequest(url_source=url),
            features=_KVP_FEATURES,                 # <-- critical for native KVPs
            output_content_format="text",           # safer for KVP parsing across SDK versions
        )
    else:
        poller = c.begin_analyze_document(
            MODEL_ID,
            content,
            content_type=content_type or "application/pdf",
            features=_KVP_FEATURES,                 # <-- critical for native KVPs
            output_content_format="text",
        )
    return poller.result()


def analyze_generic_url(doc_url: str):
    return _analyze(url=doc_url)


def analyze_generic_bytes(content: bytes, content_type: Optional[str] = None):
    if not content:
        raise ValueError("Uploaded file is empty.")
    return _analyze(content=content, content_type=content_type)


def analyze_generic_file(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    ctype, _ = mimetypes.guess_type(path)
    with open(path, "rb") as f:
        data = f.read()
    return analyze_generic_bytes(data, content_type=ctype or "application/pdf")


# ---------- SDK passthrough helpers ----------
def _shape_kv_pairs(result) -> List[Dict[str, Any]]:
    out = []
    for kv in getattr(result, "key_value_pairs", []) or []:
        key = getattr(kv, "key", None)
        val = getattr(kv, "value", None)
        out.append({
            "key": getattr(key, "content", None),
            "value": getattr(val, "content", None) if val else None,
            "key_confidence": getattr(key, "confidence", None) if key else None,
            "value_confidence": getattr(val, "confidence", None) if val else None,
        })
    return out


def _shape_tables(result) -> List[Dict[str, Any]]:
    shaped: List[Dict[str, Any]] = []

    # Prefer top-level tables if present
    top = getattr(result, "tables", None) or []
    if top:
        for t in top:
            cells = []
            for c in getattr(t, "cells", []) or []:
                cells.append({
                    "row_index": getattr(c, "row_index", None),
                    "column_index": getattr(c, "column_index", None),
                    "content": getattr(c, "content", None),
                    "confidence": getattr(c, "confidence", None),
                })
            shaped.append({
                "page_number": None,
                "row_count": getattr(t, "row_count", None),
                "column_count": getattr(t, "column_count", None),
                "cells": cells,
            })
        return shaped

    # Fallback: page-scoped tables
    for p in getattr(result, "pages", []) or []:
        for t in getattr(p, "tables", []) or []:
            cells = []
            for c in getattr(t, "cells", []) or []:
                cells.append({
                    "row_index": getattr(c, "row_index", None),
                    "column_index": getattr(c, "column_index", None),
                    "content": getattr(c, "content", None),
                    "confidence": getattr(c, "confidence", None),
                })
            shaped.append({
                "page_number": getattr(p, "page_number", None),
                "row_count": getattr(t, "row_count", None),
                "column_count": getattr(t, "column_count", None),
                "cells": cells,
            })
    return shaped


# ---------- generic KVP derivation (no schema) ----------
# Extract multiple "Label: Value" segments from a single line.
# Example: "Project No.: 1023-AE-45  Company Employee: Yes  Subcontractor Employee: No"
_SEGMENT_RE = re.compile(
    r"([A-Za-z0-9/().'’\-&, ]+?)\s*:\s*([^:]+?)(?=(?:\s+[A-Za-z].{0,30}?:|$))"
)

def _clean_label(lbl: str) -> str:
    s = (lbl or "").strip()
    # cosmetic cleanups but NOT mapping to any predefined schema
    s = re.sub(r"^\d+\.\s*", "", s)       # remove leading numbering like "5. "
    s = re.sub(r"\s+\.", ".", s)          # "No .:" -> "No.:"
    s = re.sub(r"\s+", " ", s)            # collapse spaces
    return s

def _derive_kv_from_result_lines(result) -> List[Dict[str, Any]]:
    pairs: List[Dict[str, Any]] = []
    for p in getattr(result, "pages", []) or []:
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
                    "value": value.strip() or None,
                    "key_confidence": None,
                    "value_confidence": None,
                })
    # De-duplicate (key,value) while preserving order
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for kv in pairs:
        sig = (kv["key"], kv["value"])
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(kv)
    return deduped


# ---------- public API ----------
def generic_to_dict(result) -> Dict[str, Any]:
    """
    Returns:
      {
        "key_value_pairs": [ {key,value,key_confidence,value_confidence}, ... ],
        "tables": [ ... ]
      }
    """
    sdk_pairs = _shape_kv_pairs(result)
    tables = _shape_tables(result)

    # If SDK already found kv pairs (thanks to features=keyValuePairs), keep them.
    # Otherwise, derive generically from text lines (no schema).
    key_value_pairs = sdk_pairs if sdk_pairs else _derive_kv_from_result_lines(result)

    return {
        "key_value_pairs": key_value_pairs,
        "tables": tables,
    }


def print_generic(result) -> None:
    shaped = generic_to_dict(result)
    print("--------Recognizing document (layout model)--------")
    print(f"Key-value pairs: {len(shaped.get('key_value_pairs', []))}")
    for kv in shaped.get("key_value_pairs", [])[:50]:
        print(f"{kv.get('key')}: {kv.get('value')}")
    print(f"Tables: {len(shaped.get('tables', []))}")
    print("-------------------------------------------")


# Example usage (uncomment to test locally)
# if __name__ == "__main__":
#     res = analyze_generic_file("Injury Report Form (2).pdf")
#     print_generic(res)
