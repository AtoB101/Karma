"""Karma — 操作台的安全验证（2FA / TOTP）接口。

- ``GET  /v1/console/2fa``              这个身份绑了没有 / 还锁着没有
- ``POST /v1/console/2fa/enroll``        签发一把待确认密钥（返回 otpauth 链接，操作台画二维码）
- ``POST /v1/console/2fa/activate``      验证码对得上才算绑上，同时发一次性恢复码
- ``POST /v1/console/2fa/recovery``      换一组恢复码（要过验证码）
- ``POST /v1/console/2fa/disable``       解绑（同样要过验证码）

只有身份本人（会话里的 actor == 路径 / 请求体里的 identity_id）能操作，别的一律 403。
密钥从来不回吐：``GET`` 只看得到「绑没绑、还剩几张恢复码、锁没锁」。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from services import console_2fa
from services.console_2fa import TwoFactorError
from services.identity_actor import resolve_actor_identity_id

router = APIRouter()


class CodeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: 6 位 TOTP 口令，或者一张 8 位恢复码（形如 A1B2-C3D4）。
    code: str = Field(min_length=4, max_length=32)


def _translate(exc: TwoFactorError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


async def _require_owner(db: AsyncSession, request: Request) -> str:
    """2FA 是「本人对自己身份」的动作：拿不到会话就没有主体，别人也无从代劳。

    这里只认会话里的 actor，不接受任何「帮别人绑」的参数 —— 2FA 要是能代绑，
    它就不是第二把锁了。身份卡还没领也能先绑（绑的是会话本体那个身份）。
    """
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required to manage 2FA")
    return actor


@router.get("")
async def get_two_factor(request: Request, db: AsyncSession = Depends(get_db)):
    identity_id = await _require_owner(db, request)
    return await console_2fa.status(db, identity_id)


@router.post("/enroll", status_code=201)
async def enroll_two_factor(request: Request, db: AsyncSession = Depends(get_db)):
    """签发待确认密钥。重复调用会换一把新的（上一把没确认过就等于作废）。"""
    identity_id = await _require_owner(db, request)
    try:
        payload = await console_2fa.begin_enroll(db, identity_id, account=identity_id)
    except TwoFactorError as exc:
        raise _translate(exc) from exc
    return payload


@router.post("/activate")
async def activate_two_factor(
    body: CodeBody, request: Request, db: AsyncSession = Depends(get_db)
):
    identity_id = await _require_owner(db, request)
    try:
        payload = await console_2fa.confirm_enroll(db, identity_id, body.code)
    except TwoFactorError as exc:
        raise _translate(exc) from exc
    return {**payload, **await console_2fa.status(db, identity_id)}


@router.post("/recovery")
async def rotate_recovery_codes(
    body: CodeBody, request: Request, db: AsyncSession = Depends(get_db)
):
    identity_id = await _require_owner(db, request)
    try:
        payload = await console_2fa.rotate_recovery(db, identity_id, body.code)
    except TwoFactorError as exc:
        raise _translate(exc) from exc
    return {**payload, **await console_2fa.status(db, identity_id)}


@router.post("/disable")
async def disable_two_factor(
    body: CodeBody, request: Request, db: AsyncSession = Depends(get_db)
):
    identity_id = await _require_owner(db, request)
    try:
        await console_2fa.disable(db, identity_id, body.code)
    except TwoFactorError as exc:
        raise _translate(exc) from exc
    return await console_2fa.status(db, identity_id)
