from __future__ import annotations

from fastapi import APIRouter, status

from app.models.generation import GenerationServiceRequest, GenerationServiceResponse
from app.services.generation_service import execute_generation_request

router = APIRouter(tags=["internal-generation"])


@router.post(
    "/internal/generation/run",
    response_model=GenerationServiceResponse,
    status_code=status.HTTP_200_OK,
)
async def run_generation(request: GenerationServiceRequest) -> GenerationServiceResponse:
    return await execute_generation_request(request)
