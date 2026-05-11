from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.audit import AuditEvent
from app.services.care_data import care_repository


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-Id", str(uuid4()))
        code = "http_error"
        details = None
        if isinstance(exc.detail, dict):
            code = str(exc.detail.get("code", code))
            message = str(exc.detail.get("message", code))
            details = exc.detail.get("details")
        else:
            message = str(exc.detail)

        if exc.status_code in {401, 403}:
            _record_denied_request(request, code, message, request_id)

        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error=ErrorDetail(
                    code=code,
                    message=message,
                    request_id=request_id,
                    details=details,
                )
            ).model_dump(mode="json", exclude_none=True),
        )


def _record_denied_request(
    request: Request,
    code: str,
    message: str,
    request_id: str,
) -> None:
    actor = getattr(request.state, "actor", None)
    care_repository.record_audit_event(
        AuditEvent(
            actor_id=str(actor.user_id) if actor else None,
            actor_user_id=actor.user_id if actor else None,
            patient_id=actor.patient_id if actor else None,
            action="request.denied",
            resource_type="http_request",
            outcome="denied",
            request_id=request_id,
            metadata_json={
                "method": request.method,
                "path": request.url.path,
                "error_code": code,
                "message": message,
            },
        )
    )
