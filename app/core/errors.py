from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


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
        request_id = request.headers.get("X-Request-Id", str(uuid4()))
        code = "http_error"
        details = None
        if isinstance(exc.detail, dict):
            code = str(exc.detail.get("code", code))
            message = str(exc.detail.get("message", code))
            details = exc.detail.get("details")
        else:
            message = str(exc.detail)

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
