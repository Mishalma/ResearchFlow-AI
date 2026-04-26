from __future__ import annotations

from fastapi import APIRouter, status

from app.models.validation import (
    ValidationCandidateScoringRequest,
    ValidationCandidateScoringResponse,
    ValidationServiceRequest,
    ValidationServiceResponse,
)
from app.services.validation_service import (
    execute_candidate_scoring_request,
    execute_validation_request,
)

router = APIRouter(tags=["internal-validation"])


@router.post(
    "/internal/validation/run",
    response_model=ValidationServiceResponse,
    status_code=status.HTTP_200_OK,
)
async def run_validation(request: ValidationServiceRequest) -> ValidationServiceResponse:
    return await execute_validation_request(request)


@router.post(
    "/internal/validation/score-candidates",
    response_model=ValidationCandidateScoringResponse,
    status_code=status.HTTP_200_OK,
)
async def score_candidates(
    request: ValidationCandidateScoringRequest,
) -> ValidationCandidateScoringResponse:
    return await execute_candidate_scoring_request(request)
