import os
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient

load_dotenv()

AZ_DI_ENDPOINT = os.getenv("AZ_DI_ENDPOINT_PRIMARY") or os.getenv("AZ_DI_ENDPOINT") or ""
AZ_DI_KEY      = os.getenv("AZ_DI_KEY", "")

def get_client() -> DocumentIntelligenceClient:
    if not AZ_DI_ENDPOINT or not AZ_DI_KEY:
        raise RuntimeError("Set AZ_DI_ENDPOINT_PRIMARY (or AZ_DI_ENDPOINT) and AZ_DI_KEY in environment/.env")
    return DocumentIntelligenceClient(endpoint=AZ_DI_ENDPOINT, credential=AzureKeyCredential(AZ_DI_KEY))
