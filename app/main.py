from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.services.care_data import care_repository


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="CareAgent Backend API",
        version="0.1.0",
        summary="Patient-scoped backend skeleton for the CareAgent MVP.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def persist_audit_events(request, call_next):
        response = await call_next(request)
        for event in getattr(request.state, "audit_events", []):
            care_repository.record_audit_event(event)
        return response

    install_error_handlers(app)
    app.include_router(router)
    return app


app = create_app()
