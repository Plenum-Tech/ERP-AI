from fastapi.responses import JSONResponse
from fastapi import Request
import logging, traceback, uuid

log = logging.getLogger("erp_ai")

def error_response(message: str, status: int = 500, code: str | None = None, detail: str | None = None):
    return JSONResponse(
        status_code=status,
        content={
            "ok": False,
            "code": code or f"E{status}",
            "message": message,
            "detail": detail,
        },
    )

async def catch_all_handler(request: Request, exc: Exception):
    trace_id = str(uuid.uuid4())
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log.error("Unhandled error | trace_id=%s | path=%s | exc=%s\n%s", trace_id, request.url.path, repr(exc), tb)
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "code": "E500",
            "message": "Internal server error",
            "trace_id": trace_id
        },
    )
