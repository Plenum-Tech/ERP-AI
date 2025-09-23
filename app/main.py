from fastapi import FastAPI, Request
from app.routers import upload, extract, search
from app.core.errors import catch_all_handler, error_response
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(title="ERP-AI Document Recognition", version="0.2.0")

# Global catch-all (last resort)
app.add_exception_handler(Exception, catch_all_handler)

# Optional: lightweight middleware for request logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        # This will be handled by the global exception handler, but we log here too.
        return await catch_all_handler(request, exc)

@app.get("/health")
async def health():
    try:
        return {"ok": True}
    except Exception:
        return error_response("Health check failed", 500, "EHEALTH")

app.include_router(upload.router,  prefix="/v1")
app.include_router(extract.router, prefix="/v1")
app.include_router(search.router,  prefix="/v1")
