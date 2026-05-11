"""
Karma — Authentication Middleware
Supports both JWT bearer tokens and API keys.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from jose import JWTError, jwt
from passlib.context import CryptContext

from config.settings import settings

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"sub": subject, "exp": expire, "iat": datetime.utcnow()}
    return jwt.encode(payload, settings.app_secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.app_secret_key, algorithms=[ALGORITHM])
    except JWTError as e:
        env = (settings.app_env or "").lower()
        detail = (
            f"Invalid token: {e}"
            if env in ("development", "dev", "local", "test")
            else "Invalid or expired token"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# FastAPI security schemes
# ---------------------------------------------------------------------------

bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-Karma-Api-Key", auto_error=False)


async def get_current_agent_id(
    bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    api_key: Optional[str] = Security(api_key_header),
) -> str:
    """
    Dependency: extract and validate agent identity from request.
    Accepts either JWT bearer token or X-Karma-Api-Key header.
    """
    # Try JWT first
    if bearer and bearer.credentials:
        payload = decode_access_token(bearer.credentials)
        agent_id = payload.get("sub")
        if agent_id:
            return agent_id

    # Try API key
    if api_key:
        agent_id = _validate_api_key(api_key)
        if agent_id:
            return agent_id

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _validate_api_key(api_key: str) -> Optional[str]:
    """
    Validate API key against stored hashes.
    In production: look up in DB / Redis.
    Format: karma_{agent_id}_{secret}
    """
    if not api_key.startswith("karma_"):
        return None
    parts = api_key.split("_", 2)
    if len(parts) < 3:
        return None
    return parts[1]  # agent_id


# ---------------------------------------------------------------------------
# Optional auth (for public read endpoints)
# ---------------------------------------------------------------------------

async def get_optional_agent_id(
    bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    api_key: Optional[str] = Security(api_key_header),
) -> Optional[str]:
    try:
        return await get_current_agent_id(bearer, api_key)
    except HTTPException:
        return None
