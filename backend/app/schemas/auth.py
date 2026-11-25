from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

PHONE_PATTERN = re.compile(r"^\+[1-9]\d{6,14}$")
API_HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")


class AuthStartRequest(BaseModel):
    api_id: int = Field(gt=0)
    api_hash: str = Field(min_length=32, max_length=32)
    phone: str = Field(min_length=8, max_length=32)

    @field_validator("api_hash")
    @classmethod
    def validate_api_hash(cls, value: str) -> str:
        value = value.strip()
        if not API_HASH_PATTERN.fullmatch(value):
            raise ValueError("invalid api_hash")
        return value.lower()

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        value = re.sub(r"[\s()\-]", "", value)
        if not PHONE_PATTERN.fullmatch(value):
            raise ValueError("invalid phone")
        return value


class AuthCodeRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)
    code: str = Field(pattern=r"^\d{1,10}$")


class AuthChallengeRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)


class AuthPasswordRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class AccountResponse(BaseModel):
    telegram_user_id: int
    display_name: str
    username: str | None


class AuthStatusResponse(BaseModel):
    authenticated: bool
    account: AccountResponse | None


class AuthStepResponse(BaseModel):
    challenge_id: str
    next_step: Literal["code", "password", "complete"]
    account: AccountResponse | None = None
