from uuid import UUID, uuid4

import structlog
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import RequestResponseEndpoint

from jobfit.config import Settings, get_settings
from jobfit.logging_config import configure_logging

logger = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)
    app = FastAPI(title="JobFit API", version="0.1.0")

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

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["health"])
    async def ready() -> dict[str, object]:
        return {"status": "ready", "checks": {"app": "ok", "config": "ok"}}

    return app


app = create_app()
