import os, hashlib
from dotenv import load_dotenv
from typing import Optional, Tuple, Any
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.core.exceptions import HttpResponseError

load_dotenv()
AZ_DI_ENDPOINT = os.getenv("AZ_DI_ENDPOINT_PRIMARY", "https://plenum-agent-docs.cognitiveservices.azure.com/")  # e.g., https://<name>.cognitiveservices.azure.com
AZ_DI_KEY      = os.getenv("AZ_DI_KEY", "6a31234c30864f98aba27ff1de312567")

class ModelUnavailableError(RuntimeError):
    """Raised when a requested model isn't available in the region (404/BadRequest)."""

def _client() -> DocumentIntelligenceClient:
    if not AZ_DI_ENDPOINT or not AZ_DI_KEY:
        raise RuntimeError("Document Intelligence endpoint/key not configured")
    return DocumentIntelligenceClient(endpoint=AZ_DI_ENDPOINT, credential=AzureKeyCredential(AZ_DI_KEY))

def file_sha256(buf: bytes) -> str:
    return hashlib.sha256(buf).hexdigest()

def _begin(model_id: str, *, url: Optional[str], buf: Optional[bytes]):
    di = _client()
    if url:
        return di.begin_analyze_document(model_id, AnalyzeDocumentRequest(url_source=url))
    return di.begin_analyze_document(model_id, buf)

def analyze_bytes(model_id: str, filename: str, data: bytes) -> Tuple[str, Any]:
    content_hash = file_sha256(data)
    try:
        poller = _begin(model_id, url=None, buf=data)
        return content_hash, poller.result()
    except HttpResponseError as e:
        # model not found / not available in this region
        if e.status_code == 404 or "model" in (e.message or "").lower():
            raise ModelUnavailableError(str(e)) from e
        raise

def analyze_url(model_id: str, url: str) -> Any:
    try:
        poller = _begin(model_id, url=url, buf=None)
        return poller.result()
    except HttpResponseError as e:
        if e.status_code == 404 or "model" in (e.message or "").lower():
            raise ModelUnavailableError(str(e)) from e
        raise
