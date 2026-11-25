from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from backend.app.schemas.auth import (
    AccountResponse,
    AuthChallengeRequest,
    AuthCodeRequest,
    AuthPasswordRequest,
    AuthStartRequest,
    AuthStatusResponse,
    AuthStepResponse,
)
from backend.app.telegram.session_manager import (
    AccountInfo,
    AuthStep,
    TelegramSessionManager,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def get_session_manager(request: Request) -> TelegramSessionManager:
    return request.app.state.telegram_session_manager


SessionManagerDependency = Annotated[
    TelegramSessionManager, Depends(get_session_manager)
]


def _account_response(account: AccountInfo | None) -> AccountResponse | None:
    if account is None:
        return None
    return AccountResponse(
        telegram_user_id=account.telegram_user_id,
        display_name=account.display_name,
        username=account.username,
    )


def _step_response(step: AuthStep) -> AuthStepResponse:
    return AuthStepResponse(
        challenge_id=step.challenge_id,
        next_step=step.next_step,
        account=_account_response(step.account),
    )


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(
    manager: SessionManagerDependency,
) -> AuthStatusResponse:
    account = await manager.status()
    return AuthStatusResponse(
        authenticated=account is not None,
        account=_account_response(account),
    )


@router.post("/start", response_model=AuthStepResponse)
async def auth_start(
    payload: AuthStartRequest,
    manager: SessionManagerDependency,
) -> AuthStepResponse:
    step = await manager.start(payload.api_id, payload.api_hash, payload.phone)
    return _step_response(step)


@router.post("/verify-code", response_model=AuthStepResponse)
async def verify_code(
    payload: AuthCodeRequest,
    manager: SessionManagerDependency,
) -> AuthStepResponse:
    step = await manager.verify_code(payload.challenge_id, payload.code)
    return _step_response(step)


@router.post("/resend-code", response_model=AuthStepResponse)
async def resend_code(
    payload: AuthChallengeRequest,
    manager: SessionManagerDependency,
) -> AuthStepResponse:
    step = await manager.resend_code(payload.challenge_id)
    return _step_response(step)


@router.post("/verify-password", response_model=AuthStepResponse)
async def verify_password(
    payload: AuthPasswordRequest,
    manager: SessionManagerDependency,
) -> AuthStepResponse:
    step = await manager.verify_password(payload.challenge_id, payload.password)
    return _step_response(step)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    manager: SessionManagerDependency,
) -> Response:
    await manager.logout()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
