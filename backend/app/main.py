from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.export import router as export_router
from app.api.routes.figure import router as figure_router
from app.api.routes.generate import router as generate_router
from app.api.routes.health import router as health_router
from app.api.routes.project import router as project_router
from app.api.routes.save import router as save_router
from app.api.routes.upload import router as upload_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.services.file_service import ensure_upload_dir
from services.figure_service import ensure_figure_dir

settings = get_settings()
settings.static_dir.mkdir(parents=True, exist_ok=True)
settings.figures_dir.mkdir(parents=True, exist_ok=True)
settings.outputs_dir.mkdir(parents=True, exist_ok=True)
settings.templates_dir.mkdir(parents=True, exist_ok=True)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )


configure_logging()
logger = logging.getLogger("papereasy.backend")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_upload_dir(settings.uploads_dir)
    ensure_figure_dir(settings.figures_dir)
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Upload directory ready at %s", settings.uploads_dir)
    logger.info("Figure directory ready at %s", settings.figures_dir)
    logger.info("Output directory ready at %s", settings.outputs_dir)
    yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=settings.static_dir, check_dir=False), name="static")
app.mount("/outputs", StaticFiles(directory=settings.outputs_dir, check_dir=False), name="outputs")


@app.exception_handler(AppError)
async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


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
            "Unhandled application error while serving %s %s",
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
app.include_router(upload_router)
app.include_router(project_router)
app.include_router(save_router)
app.include_router(figure_router)
app.include_router(export_router)
app.include_router(generate_router)
