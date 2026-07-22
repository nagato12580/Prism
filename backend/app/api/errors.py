# backend/app/api/errors.py
from fastapi import Request
from fastapi.responses import JSONResponse


class ApiProblem(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict | None = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}


async def api_problem_handler(request: Request, exc: ApiProblem) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", "")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
                "details": exc.details,
                "trace_id": trace_id,
            }
        },
    )
