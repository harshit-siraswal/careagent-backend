from collections import defaultdict, deque
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.services.care_data import care_repository


SENSITIVE_RATE_LIMIT_PATHS = (
    "/auth",
    "/agent",
    "/risk-events",
    "/escalation-runs",
)
_rate_limit_hits: dict[str, deque[float]] = defaultdict(deque)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="CareAgent Backend API",
        version="0.1.0",
        summary="Patient-scoped backend skeleton for the CareAgent MVP.",
        docs_url="/docs" if settings.api_docs_enabled else None,
        redoc_url="/redoc" if settings.api_docs_enabled else None,
        openapi_url="/openapi.json" if settings.api_docs_enabled else None,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.trusted_hosts,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_lifecycle(request, call_next):
        request_id = request.headers.get("X-Request-Id") or str(uuid4())
        request.state.request_id = request_id
        content_length = request.headers.get("content-length")
        try:
            body_size = int(content_length) if content_length else 0
        except ValueError:
            body_size = settings.max_request_body_bytes + 1
        if body_size > settings.max_request_body_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "request_body_too_large",
                        "message": "Request body exceeds the configured limit.",
                        "request_id": request_id,
                    }
                },
            )
        if _is_sensitive_path(request.url.path) and _rate_limited(request, settings):
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": "Too many requests. Try again later.",
                        "request_id": request_id,
                    }
                },
            )
        response = await call_next(request)
        for event in getattr(request.state, "audit_events", []):
            care_repository.record_audit_event(event)
        response.headers["X-Request-Id"] = request_id
        return response

    install_error_handlers(app)
    app.include_router(router)
    return app


app = create_app()


def _is_sensitive_path(path: str) -> bool:
    return path.startswith(SENSITIVE_RATE_LIMIT_PATHS)


def _rate_limited(request, settings) -> bool:
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{request.url.path}"
    now = monotonic()
    hits = _rate_limit_hits[key]
    while hits and now - hits[0] > settings.rate_limit_window_seconds:
        hits.popleft()
    if len(hits) >= settings.rate_limit_sensitive_requests:
        return True
    hits.append(now)
    return False
