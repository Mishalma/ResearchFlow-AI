from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.core.config import get_settings
from originality.utils import persist_callback_payload

router = APIRouter(tags=["originality-webhooks"])


@router.post(
    "/webhooks/originality/copyleaks/status/{scan_id}/{status_name}",
    status_code=status.HTTP_200_OK,
)
async def receive_copyleaks_status_webhook(
    scan_id: str,
    status_name: str,
    request: Request,
) -> dict[str, bool]:
    payload = await request.json()
    settings = get_settings()
    persist_callback_payload(
        base_dir=settings.temp_dir,
        scan_id=scan_id,
        event_name=f"status-{status_name}",
        payload=payload,
    )
    return {"ok": True}


@router.post(
    "/webhooks/originality/copyleaks/export/{scan_id}/completed",
    status_code=status.HTTP_200_OK,
)
async def receive_copyleaks_export_completed_webhook(
    scan_id: str,
    request: Request,
) -> dict[str, bool]:
    payload = await request.json()
    settings = get_settings()
    persist_callback_payload(
        base_dir=settings.temp_dir,
        scan_id=scan_id,
        event_name="export-completed",
        payload=payload,
    )
    return {"ok": True}


@router.post(
    "/webhooks/originality/copyleaks/export/{scan_id}/result/{result_id}",
    status_code=status.HTTP_200_OK,
)
async def receive_copyleaks_result_webhook(
    scan_id: str,
    result_id: str,
    request: Request,
) -> dict[str, bool]:
    payload = await request.json()
    settings = get_settings()
    persist_callback_payload(
        base_dir=settings.temp_dir,
        scan_id=scan_id,
        event_name=f"result-{result_id}",
        payload=payload,
    )
    return {"ok": True}
