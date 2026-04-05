from fastapi import APIRouter, status

router = APIRouter(tags=["health"])


@router.get("/", status_code=status.HTTP_200_OK)
async def root() -> dict[str, str]:
    return {
        "status": "ok",
        "message": "PaperEasy backend is running",
        "health_url": "/health",
        "docs_url": "/docs",
    }


@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "message": "Backend is running",
    }
