"""FastAPI 의존성 (인증/세션)."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token, hash_personal_code
from app.db.base import get_db
from app.db.models import AdminUser, Conversation, UserSession, utcnow

bearer_scheme = HTTPBearer(auto_error=False, description="관리자 JWT")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_session(
    x_personal_code: str | None = Header(default=None, alias="X-Personal-Code"),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> UserSession:
    """개인 코드로 비회원 세션을 인증한다.

    X-Personal-Code 헤더를 우선 사용하고, 없으면 Authorization: Bearer <code>도 허용한다.
    (JWT 형태는 관리자 인증에서만 사용)
    """
    code = (x_personal_code or "").strip()
    if not code and authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.count(".") != 2:
            code = token.strip()
    if not code:
        raise _unauthorized("개인 코드가 필요합니다. X-Personal-Code 헤더를 사용하세요.")

    digest = hash_personal_code(code)
    session = (
        await db.execute(
            select(UserSession).where(
                UserSession.code_hash == digest,
                UserSession.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise _unauthorized("유효하지 않은 개인 코드입니다.")

    session.last_seen_at = utcnow()
    await db.commit()
    return session


async def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> AdminUser:
    if credentials is None:
        raise _unauthorized("관리자 토큰이 필요합니다.")
    try:
        payload = decode_access_token(credentials.credentials)
    except Exception as exc:  # PyJWTError 포함
        raise _unauthorized("토큰이 유효하지 않거나 만료되었습니다.") from exc

    admin_id = payload.get("sub")
    if not admin_id:
        raise _unauthorized("토큰이 유효하지 않습니다.")
    admin = await db.get(AdminUser, admin_id)
    if admin is None or not admin.is_active:
        raise _unauthorized("관리자 계정을 찾을 수 없습니다.")
    return admin


async def get_owned_conversation(
    db: AsyncSession, session_id: str, conversation_id: str
) -> Conversation:
    conversation = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.session_id == session_id,
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")
    return conversation
