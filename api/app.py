import asyncio
import json
from typing import Annotated, Any
from uuid import UUID, uuid4

import structlog
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.middleware.base import RequestResponseEndpoint

from api.store import analysis_store
from jobfit.config import Settings, get_settings
from jobfit.logging_config import configure_logging
from worker.tasks import run_analysis

logger = structlog.get_logger(__name__)


def _problem_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    title: str,
    detail: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        media_type="application/problem+json",
        content={
            "type": "about:blank",
            "title": title,
            "status": status_code,
            "detail": detail,
            "instance": str(request.url.path),
            "code": code,
        },
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)
    app = FastAPI(title="JobFit API", version="0.1.0")
    app.state.analysis_store = analysis_store

    @app.middleware("http")
    async def add_request_context(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        incoming_request_id = request.headers.get("X-Request-ID")
        try:
            request_id = str(UUID(incoming_request_id))
        except (TypeError, ValueError):
            request_id = str(uuid4())

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
            )
            return response
        except Exception as exc:
            logger.error("request_failed", error_type=type(exc).__name__)
            raise
        finally:
            structlog.contextvars.clear_contextvars()

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict):
            detail_text = str(detail)
        else:
            detail_text = str(detail)
        return _problem_response(
            request,
            status_code=exc.status_code,
            code="REQUEST_ERROR",
            title="Request failed",
            detail=detail_text,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception("Unhandled request error", error_type=type(exc).__name__)
        return _problem_response(
            request,
            status_code=500,
            code="INTERNAL_ERROR",
            title="Internal error",
            detail="An unexpected error occurred while processing the request.",
        )

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["health"])
    async def ready() -> dict[str, object]:
        return {"status": "ready", "checks": {"app": "ok", "config": "ok"}}

    @app.post("/api/v1/analyses", status_code=202, tags=["analyses"])
    async def create_analysis(
        resume_file: Annotated[UploadFile, File(...)],
        job_url: Annotated[str | None, Form()] = None,
        job_text: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        if not job_url and not job_text:
            raise HTTPException(
                status_code=400,
                detail="Either job_url or job_text must be supplied.",
            )
        if not resume_file.filename:
            raise HTTPException(
                status_code=400,
                detail="A resume file is required to create an analysis.",
            )

        raw_resume = await resume_file.read()
        if not raw_resume:
            raise HTTPException(
                status_code=400,
                detail="The uploaded resume file is empty.",
            )

        resume_text = raw_resume.decode("utf-8", errors="replace")
        record = analysis_store.create(
            job_url=job_url,
            job_text=job_text,
            resume_text=resume_text,
        )

        asyncio.create_task(
            run_analysis(
                record.analysis_id,
                resume_text=resume_text,
                job_text=job_text or job_url or "",
                source="pasted" if job_text else "url",
            )
        )

        return {
            "analysis_id": record.analysis_id,
            "status": record.status,
            "status_url": f"/api/v1/analyses/{record.analysis_id}",
            "message": record.message,
        }

    @app.get("/api/v1/analyses/{analysis_id}", tags=["analyses"])
    async def get_analysis_status(analysis_id: str) -> dict[str, Any]:
        record = analysis_store.get(analysis_id)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail=f"Analysis '{analysis_id}' was not found.",
            )

        return {
            "analysis_id": record.analysis_id,
            "status": record.status,
            "progress": record.progress,
            "message": record.message,
            "result": record.result,
        }

    @app.get("/api/v1/analyses/{analysis_id}/events", tags=["analyses"])
    async def analysis_events(analysis_id: str) -> StreamingResponse:
        record = analysis_store.get(analysis_id)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail=f"Analysis '{analysis_id}' was not found.",
            )

        async def event_stream() -> Any:
            last_status: str | None = None
            while True:
                current = analysis_store.get(analysis_id)
                if current is None:
                    yield "event: error\n"
                    yield 'data: {"code":"ANALYSIS_NOT_FOUND"}\n\n'
                    break
                if last_status != current.status:
                    payload = {
                        "analysis_id": current.analysis_id,
                        "status": current.status,
                        "progress": current.progress,
                        "message": current.message,
                    }
                    yield "event: status\n"
                    yield f"data: {json.dumps(payload)}\n\n"
                    last_status = current.status
                if current.status in {"completed", "failed"}:
                    break
                await asyncio.sleep(0.05)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app


app = create_app()
