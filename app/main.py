from fastapi import FastAPI

from app.api.routes import router
from app.core.errors import install_error_handlers


def create_app() -> FastAPI:
    app = FastAPI(
        title="CareAgent Backend API",
        version="0.1.0",
        summary="Patient-scoped backend skeleton for the CareAgent MVP.",
    )
    install_error_handlers(app)
    app.include_router(router)
    return app


app = create_app()
