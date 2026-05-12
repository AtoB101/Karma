"""
Karma — Authentication Middleware
Supports both JWT bearer tokens and API keys.
"""
from __future__ import annotations

import hmac
import re
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
import structlog

from jose import JWTError, jwt
from passlib.context import CryptContext

from config.settings import settings

logger = structlog.get_logger(__name__)

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
_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$")


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
    parsed = _parse_api_key(api_key)
    if not parsed:
        return None
    agent_id, secret = parsed
    if not _AGENT_ID_RE.match(agent_id):
        return None
    configured = settings.auth_api_keys_map()
    expected = configured.get(agent_id)
    if expected is not None:
        return agent_id if hmac.compare_digest(secret, expected) else None

    # Backward-compatible development fallback only.
    env = (settings.app_env or "").lower()
    if (not settings.auth_enforce_protected_routes) and env in ("development", "dev", "local", "test") and len(secret) >= 12:
        return agent_id
    return None


def validate_api_key_for_agent(agent_id: str, api_key: str) -> bool:
    parsed = _parse_api_key(api_key)
    if not parsed:
        return False
    parsed_agent_id, _ = parsed
    if parsed_agent_id != agent_id:
        return False
    resolved_agent_id = _validate_api_key(api_key)
    return resolved_agent_id == agent_id


def _parse_api_key(api_key: str) -> Optional[tuple[str, str]]:
    if not api_key.startswith("karma_"):
        return None
    parts = api_key.split("_", 2)
    if len(parts) < 3:
        return None
    return parts[1], parts[2]


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


def resolve_agent_id_from_auth_headers(
    *,
    authorization: str | None,
    api_key: str | None,
) -> Optional[str]:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token:
            try:
                payload = decode_access_token(token)
                subject = payload.get("sub")
                if isinstance(subject, str) and subject:
                    return subject
            except HTTPException:
                pass
    if api_key:
        return _validate_api_key(api_key)
    return None


async def require_auth_if_enabled(
    request: Request,
    agent_id: Optional[str] = Depends(get_optional_agent_id),
) -> None:
    if settings.auth_enforce_protected_routes and not agent_id:
        logger.warning(
            "auth_required_for_protected_route",
            method=request.method,
            path=request.url.path,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
