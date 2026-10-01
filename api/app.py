import asyncio
import json
import os
import time
from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID, uuid4

import structlog
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.middleware.base import RequestResponseEndpoint

from api.store import analysis_store
from jobfetch.fetcher import JobFetcher, JobFetchError
from jobfit.config import Settings, get_settings
from jobfit.logging_config import configure_logging
from worker.tasks import run_analysis


class PolicyError(HTTPException):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        title: str,
        detail: str,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code
        self.title = title


class CircuitBreaker:
    def __init__(self, *, failure_threshold: int = 5, reset_seconds: int = 60) -> None:
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.failure_count = 0
        self.state = "closed"
        self.opened_at: float | None = None

    def allow(self) -> bool:
        if self.state == "open":
            if (
                self.opened_at is None
                or time.time() - self.opened_at >= self.reset_seconds
            ):
                self.state = "half-open"
                self.failure_count = 0
                return True
            return False
        return True

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = "closed"
        self.opened_at = None

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            self.opened_at = time.time()


class BudgetTracker:
    def __init__(self, *, max_cost_usd: float = 25.0) -> None:
        self.max_cost_usd = max_cost_usd
        self.spending: dict[str, float] = {}

    def consume(self, user_id: str, amount: float) -> bool:
        current = self.spending.get(user_id, 0.0)
        next_total = current + amount
        if next_total > self.max_cost_usd:
            return False
        self.spending[user_id] = next_total
        return True


def _get_client_key(request: Request) -> str | None:
    api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization")
    if api_key is None:
        return None
    if api_key.lower().startswith("bearer "):
        api_key = api_key[7:]
    return api_key.strip() or None


def _resolve_user_id(request: Request, app: FastAPI) -> str | None:
    api_key = _get_client_key(request)
    if not api_key:
        return None
    api_keys = getattr(app.state, "api_keys", {})
    if not isinstance(api_keys, dict):
        return None
    return api_keys.get(api_key)


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
    app.state.job_fetcher = JobFetcher()
    app.state.api_keys = {
        key: value
        for key, value in {
            os.getenv("JOBFIT_API_KEY"): os.getenv("JOBFIT_API_USER", "demo-user"),
        }.items()
        if key
    }
    app.state.rate_limiter = {}
    app.state.budget_tracker = BudgetTracker(
        max_cost_usd=float(os.getenv("JOBFIT_DAILY_BUDGET_USD", "25.0"))
    )
    app.state.circuit_breaker = CircuitBreaker()

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

    @app.exception_handler(PolicyError)
    async def policy_exception_handler(
        request: Request,
        exc: PolicyError,
    ) -> JSONResponse:
        return _problem_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            title=exc.title,
            detail=str(exc.detail),
        )

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

    def enforce_rate_limit(request: Request) -> str | None:
        api_key = _get_client_key(request)
        if not api_key:
            return None
        user_id = _resolve_user_id(request, app)
        if not user_id:
            raise PolicyError(
                status_code=401,
                code="AUTH_REQUIRED",
                title="Authentication required",
                detail="A valid API key is required.",
            )

        limiter = getattr(app.state, "rate_limiter", {})
        if not isinstance(limiter, dict):
            return user_id

        window_seconds = 60
        limit = 10
        bucket = limiter.get(
            user_id,
            {"requests": [], "limit": limit, "window_seconds": window_seconds},
        )
        current = time.time()
        bucket["requests"] = [
            ts
            for ts in bucket.get("requests", [])
            if current - ts < bucket["window_seconds"]
        ]
        if len(bucket["requests"]) >= bucket["limit"]:
            raise PolicyError(
                status_code=429,
                code="RATE_LIMITED",
                title="Rate limit exceeded",
                detail="Rate limit exceeded for this user.",
            )
        bucket["requests"].append(current)
        limiter[user_id] = bucket
        return user_id

    def require_authenticated_user(request: Request) -> str:
        user_id = _resolve_user_id(request, app)
        if not user_id:
            raise PolicyError(
                status_code=401,
                code="AUTH_REQUIRED",
                title="Authentication required",
                detail="Authentication required.",
            )
        return user_id

    @app.middleware("http")
    async def enforce_user_limits(
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        try:
            if request.url.path in {"/health", "/ready"}:
                return await call_next(request)

            is_history_or_account = request.url.path.startswith(
                "/api/v1/history"
            ) or request.url.path.startswith("/api/v1/account")
            if is_history_or_account:
                require_authenticated_user(request)
            if _get_client_key(request) and request.url.path.startswith("/api/v1"):
                enforce_rate_limit(request)
            response = await call_next(request)
            return response
        except PolicyError as exc:
            return _problem_response(
                request,
                status_code=exc.status_code,
                code=exc.code,
                title=exc.title,
                detail=str(exc.detail),
            )

    @app.get("/api/v1/history", tags=["history"])
    async def get_history(request: Request) -> dict[str, Any]:
        user_id = require_authenticated_user(request)
        records = [
            {
                "analysis_id": record.analysis_id,
                "status": record.status,
                "progress": record.progress,
                "message": record.message,
                "result": record.result,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
            for record in app.state.analysis_store.list_for_user(user_id)
        ]
        return {"items": records}

    @app.delete("/api/v1/analyses/{analysis_id}", tags=["analyses"])
    async def delete_analysis(analysis_id: str, request: Request) -> dict[str, Any]:
        user_id = require_authenticated_user(request)
        deleted = app.state.analysis_store.delete(analysis_id, user_id=user_id)
        if not deleted:
            raise PolicyError(
                status_code=404,
                code="ANALYSIS_NOT_FOUND",
                title="Analysis not found",
                detail=f"Analysis '{analysis_id}' was not found for this user.",
            )
        return {"analysis_id": analysis_id, "deleted": True}

    @app.delete("/api/v1/account", tags=["account"])
    async def delete_account(request: Request) -> dict[str, Any]:
        user_id = require_authenticated_user(request)
        removed = [
            record.analysis_id
            for record in app.state.analysis_store.list_for_user(user_id)
        ]
        for analysis_id in removed:
            app.state.analysis_store.delete(analysis_id, user_id=user_id)
        return {"deleted": True, "analysis_ids": removed}

    @app.post("/api/v1/extract-job", tags=["job"])
    async def extract_job(request: Request) -> dict[str, Any]:
        payload = await request.json()
        url = payload.get("url") if isinstance(payload, dict) else None
        if not isinstance(url, str) or not url.strip():
            raise HTTPException(
                status_code=400,
                detail="A job URL is required for extraction.",
            )
        try:
            fetched = app.state.job_fetcher.fetch(url)
        except JobFetchError as exc:
            return _problem_response(
                request,
                status_code=400,
                code=exc.code,
                title="Job link unreadable",
                detail=exc.args[0] if exc.args else str(exc),
            )

        return {
            "title": fetched.title,
            "text": fetched.text,
            "source": fetched.source,
            "url": fetched.url,
        }

    @app.post("/api/v1/analyses", status_code=202, tags=["analyses"])
    async def create_analysis(
        request: Request,
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

        if _get_client_key(request):
            user_id = require_authenticated_user(request)
            if not app.state.circuit_breaker.allow():
                raise PolicyError(
                    status_code=503,
                    code="LLM_UNAVAILABLE",
                    title="Service unavailable",
                    detail="The job-matching service is temporarily unavailable.",
                )
            if not app.state.budget_tracker.consume(user_id, 0.05):
                raise PolicyError(
                    status_code=429,
                    code="BUDGET_EXCEEDED",
                    title="Budget exceeded",
                    detail="Daily budget exhausted for this user.",
                )
        else:
            user_id = None

        resume_text = raw_resume.decode("utf-8", errors="replace")
        record = analysis_store.create(
            job_url=job_url,
            job_text=job_text,
            resume_text=resume_text,
            user_id=user_id,
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
