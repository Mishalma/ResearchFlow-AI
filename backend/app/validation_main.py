from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes.health import router as health_router
from app.api.routes.internal_validation import router as internal_validation_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.services.file_service import ensure_upload_dir
from persistence import get_object_storage, get_project_repository
from services.figure_service import ensure_figure_dir
from validation.config import ValidationConfig
from validation.desklib_detector import warm_desklib_detector

settings = get_settings()
settings.static_dir.mkdir(parents=True, exist_ok=True)
settings.figures_dir.mkdir(parents=True, exist_ok=True)
settings.outputs_dir.mkdir(parents=True, exist_ok=True)
settings.local_projects_dir.mkdir(parents=True, exist_ok=True)
settings.local_jobs_dir.mkdir(parents=True, exist_ok=True)
settings.templates_dir.mkdir(parents=True, exist_ok=True)
settings.temp_dir.mkdir(parents=True, exist_ok=True)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )


configure_logging()
logger = logging.getLogger("papereasy.validation_service")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_upload_dir(settings.uploads_dir)
    ensure_figure_dir(settings.figures_dir)
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    settings.local_projects_dir.mkdir(parents=True, exist_ok=True)
    settings.local_jobs_dir.mkdir(parents=True, exist_ok=True)
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    get_project_repository()
    get_object_storage()
    validation_config = ValidationConfig.from_settings(settings)
    warm_desklib_detector(
        validation_config,
        project_id=settings.google_cloud_project,
    )
    logger.info("Validation service ready with persistence backend: %s", settings.persistence_backend)
    yield


app = FastAPI(title=f"{settings.app_name} Validation Service", debug=settings.debug, lifespan=lifespan)


@app.exception_handler(AppError)
async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
    content = {"error": exc.message}
    if exc.details:
        content["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    message = "Invalid request payload."
    if exc.errors():
        message = exc.errors()[0].get("msg", message)

    return JSONResponse(status_code=422, content={"error": message})


@app.middleware("http")
async def log_requests_and_handle_errors(request: Request, call_next):
    start_time = perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "Unhandled validation service error while serving %s %s",
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error"},
        )

    duration_ms = (perf_counter() - start_time) * 1000
    logger.info(
        "%s %s -> %s (%.2f ms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


app.include_router(health_router)
app.include_router(internal_validation_router)
