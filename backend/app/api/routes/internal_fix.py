from __future__ import annotations

from fastapi import APIRouter, status

from app.models.fix import FixServiceRequest, FixServiceResponse
from app.services.fix_service import execute_fix_service_request

router = APIRouter(tags=["internal-fix"])


@router.post(
    "/internal/fix/run",
    response_model=FixServiceResponse,
    status_code=status.HTTP_200_OK,
)
async def run_fix(request: FixServiceRequest) -> FixServiceResponse:
    return await execute_fix_service_request(request)
