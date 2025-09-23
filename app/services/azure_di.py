# app/services/azure_di.py
import os
import aiohttp
import asyncio
import logging
from urllib.parse import urljoin
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("erp_ai.azure_di")

# ------------------------------
# Env / config
# ------------------------------
ENDPOINT  = (os.getenv("AZURE_DI_ENDPOINT") or "").rstrip("/")
KEY       = os.getenv("AZURE_DI_KEY") or ""
# Preferred API version if you want to pin; we still try others as fallbacks.
PINNED_API_VER = os.getenv("AZURE_DI_API_VERSION", "").strip()

# Try these in order if AZURE_DI_API_VERSION isn't pinned or fails
V4_VERSIONS   = [v for v in [PINNED_API_VER, "2024-07-31-preview", "2024-02-29-preview"] if v]
V31_VERSIONS  = [v for v in [PINNED_API_VER, "2023-07-31", "2022-08-31"] if v]

MODEL_BY_TYPE = {
    "passport":       os.getenv("MODEL_PASSPORT",       "prebuilt-idDocument"),
    "visa":           os.getenv("MODEL_VISA",           "prebuilt-idDocument"),
    "work_permit":    os.getenv("MODEL_WORKPERMIT",     "prebuilt-idDocument"),
    "invoice":        os.getenv("MODEL_INVOICE",        "prebuilt-invoice"),
    "bank_statement": os.getenv("MODEL_BANKSTMT",       "prebuilt-bankStatement"),
    "resume":         os.getenv("MODEL_RESUME",         "prebuilt-document"),
    "injury_report":  os.getenv("MODEL_INJURY",         "prebuilt-document"),
}

# ------------------------------
# Helpers
# ------------------------------
def _candidate_urls(model: str, api_ver: str):
    """Yield both API families for a given model/version (v3.1 + v4)."""
    return [
        f"{ENDPOINT}/formrecognizer/documentModels/{model}:analyze?api-version={api_ver}",          # v3.1 family
        f"{ENDPOINT}/documentintelligence/documentModels/{model}:analyze?api-version={api_ver}",    # v4 family
    ]

def _ensure_config():
    if not ENDPOINT or not KEY:
        raise RuntimeError(
            "Azure DI not configured. Set AZURE_DI_ENDPOINT (…cognitiveservices.azure.com) "
            "and AZURE_DI_KEY in your environment/.env"
        )
    if ".openai." in ENDPOINT:
        raise RuntimeError(
            "AZURE_DI_ENDPOINT points to an Azure OpenAI resource. "
            "You must use a Cognitive Services endpoint (…cognitiveservices.azure.com)."
        )

async def _submit(session: aiohttp.ClientSession, url: str, file_bytes: bytes, content_type: str):
    headers = {"Ocp-Apim-Subscription-Key": KEY, "Content-Type": content_type or "application/pdf"}
    resp = await session.post(url, headers=headers, data=file_bytes)
    text = await resp.text()
    # 202: LRO with operation-location; 200: sometimes inline body (preview behavior)
    if resp.status not in (200, 202):
        raise RuntimeError(f"submit {resp.status}: {text} @ {url}")
    return resp, text

async def _poll(session: aiohttp.ClientSession, op_url: str, timeout_sec: int = 120):
    headers = {"Ocp-Apim-Subscription-Key": KEY}
    deadline = asyncio.get_running_loop().time() + timeout_sec
    while True:
        r = await session.get(op_url, headers=headers)
        js = await r.json(content_type=None)
        status = (js.get("status") or js.get("analysisStatus") or "").lower()
        if status in ("succeeded", "partiallysucceeded", "failed"):
            if status == "failed":
                raise RuntimeError(f"poll failed: {js}")
            return js
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError("Azure DI polling timed out")
        await asyncio.sleep(1.0)

# ------------------------------
# Public entry
# ------------------------------
async def analyze(doc_type: str, file_bytes: bytes, content_type: str = "application/pdf") -> dict:
    """
    Analyze a document with Azure Document Intelligence / Form Recognizer.
    Tries v4 & v3.1 families and falls back to layout/general where appropriate.
    """
    # Dev fallback (so local dev doesn't block)
    if not ENDPOINT or not KEY:
        log.warning("Azure DI not configured; returning dummy result for doc_type=%s", doc_type)
        return {
            "status": "succeeded",
            "analyzeResult": {
                "documents": [{"fields": {"DocumentNumber": {"content": "P1234567"}}}],
                "pages": [{"lines": [{"content": "Dummy OCR"}]}],
            },
        }

    _ensure_config()

    model_primary = MODEL_BY_TYPE.get(doc_type, "prebuilt-document")
    timeout = aiohttp.ClientTimeout(total=300)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        # ---------- 1) Try preferred model across v4 then v3.1 ----------
        for ver in (V4_VERSIONS + V31_VERSIONS):
            for url in _candidate_urls(model_primary, ver):
                try:
                    resp, body_text = await _submit(session, url, file_bytes, content_type)

                    # If 202: poll the operation
                    op = resp.headers.get("operation-location")
                    if op:
                        op_url = op if op.startswith("http") else urljoin(ENDPOINT + "/", op.lstrip("/"))
                        return await _poll(session, op_url)

                    # If 200: some previews return inline body
                    try:
                        js = await resp.json(content_type=None)
                        if "analyzeResult" in js or "status" in js:
                            return js
                    except Exception:
                        pass  # fall through

                    # No op header and no parseable body => treat as failure and continue
                    log.info("Azure DI: no operation-location and no inline body for %s", url)

                except Exception as e:
                    msg = str(e)
                    # 404 is common when a model isn't in that family/version; keep trying
                    if " 404:" in msg or " submit 404:" in msg:
                        log.info("Azure DI 404 for %s: %s", url, msg)
                        continue
                    # Other errors: try next candidate, but record for context
                    log.info("Azure DI error for %s: %s", url, msg)
                    continue

        # ---------- 2) Fallbacks ----------
        # (a) bank statement → try layout, then general
        if doc_type == "bank_statement":
            for ver in (V4_VERSIONS + V31_VERSIONS):
                for url in _candidate_urls("prebuilt-layout", ver):
                    try:
                        resp, _ = await _submit(session, url, file_bytes, content_type)
                        op = resp.headers.get("operation-location")
                        if op:
                            op_url = op if op.startswith("http") else urljoin(ENDPOINT + "/", op.lstrip("/"))
                            return await _poll(session, op_url)
                        try:
                            js = await resp.json(content_type=None)
                            if "analyzeResult" in js or "status" in js:
                                return js
                        except Exception:
                            pass
                    except Exception as e:
                        if " 404:" in str(e):
                            continue

        # (b) final fallback → general document
        for ver in (V4_VERSIONS + V31_VERSIONS):
            for url in _candidate_urls("prebuilt-document", ver):
                try:
                    resp, _ = await _submit(session, url, file_bytes, content_type)
                    op = resp.headers.get("operation-location")
                    if op:
                        op_url = op if op.startswith("http") else urljoin(ENDPOINT + "/", op.lstrip("/"))
                        return await _poll(session, op_url)
                    try:
                        js = await resp.json(content_type=None)
                        if "analyzeResult" in js or "status" in js:
                            return js
                    except Exception:
                        pass
                except Exception as e:
                    if " 404:" in str(e):
                        continue

    # If we reached here, every candidate was rejected
    raise RuntimeError(
        "Azure DI: all routes failed.\n"
        f"Endpoint: {ENDPOINT}\n"
        f"Primary model tried: {model_primary}\n"
        f"Versions tried: {', '.join(set(V4_VERSIONS + V31_VERSIONS))}\n"
        "Common causes:\n"
        "  • Endpoint/key mismatch or wrong Cognitive Services resource.\n"
        "  • Model not available in this API family/region.\n"
        "  • Using an OpenAI endpoint instead of Cognitive Services."
    )
