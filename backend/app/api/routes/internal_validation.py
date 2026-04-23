from __future__ import annotations

from fastapi import APIRouter, status

from app.models.validation import ValidationServiceRequest, ValidationServiceResponse
from app.services.validation_service import execute_validation_request

router = APIRouter(tags=["internal-validation"])


@router.post(
    "/internal/validation/run",
    response_model=ValidationServiceResponse,
    status_code=status.HTTP_200_OK,
)
async def run_validation(request: ValidationServiceRequest) -> ValidationServiceResponse:
    return await execute_validation_request(request)
