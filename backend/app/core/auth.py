from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Header

from app.core.exceptions import AuthenticationRequiredError

TRUSTED_USER_ID_HEADER = "X-PaperEasy-User-Id"
TRUSTED_USER_EMAIL_HEADER = "X-PaperEasy-User-Email"
TRUSTED_USER_NAME_HEADER = "X-PaperEasy-User-Name"


@dataclass(frozen=True)
class AuthenticatedRequestUser:
    user_id: str
    email: str
    display_name: str


async def get_authenticated_user(
    x_papereasy_user_id: Annotated[str | None, Header(alias=TRUSTED_USER_ID_HEADER)] = None,
    x_papereasy_user_email: Annotated[str | None, Header(alias=TRUSTED_USER_EMAIL_HEADER)] = None,
    x_papereasy_user_name: Annotated[str | None, Header(alias=TRUSTED_USER_NAME_HEADER)] = None,
) -> AuthenticatedRequestUser:
    user_id = (x_papereasy_user_id or "").strip()
    email = (x_papereasy_user_email or "").strip().lower()
    display_name = (x_papereasy_user_name or email or "PaperEasy User").strip()

    if not user_id or not email:
        raise AuthenticationRequiredError()

    return AuthenticatedRequestUser(
        user_id=user_id,
        email=email,
        display_name=display_name,
    )
