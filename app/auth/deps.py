"""Authentication dependencies: JWT and API key support."""

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings

_api_key_header = APIKeyHeader(name=settings.api_key_header, auto_error=False)
_bearer = HTTPBearer(auto_error=False)


def _decode_jwt(token: str) -> dict:
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )


def _valid_api_keys_set() -> set[str]:
    if not settings.api_keys:
        return set()
    return {k.strip() for k in settings.api_keys.split(",") if k.strip()}


def get_user_id_from_api_key(api_key: str | None) -> str | None:
    """Return user identifier if API key is valid. Otherwise None."""
    if not api_key:
        return None
    keys = _valid_api_keys_set()
    if keys and api_key in keys:
        return f"api:{api_key[:8]}"
    return None


def get_user_id_from_jwt(credentials: HTTPAuthorizationCredentials | None) -> str | None:
    """Return user identifier from JWT sub claim if valid. Otherwise None."""
    if not credentials or credentials.scheme.lower() != "bearer":
        return None
    try:
        payload = _decode_jwt(credentials.credentials)
        user = payload.get("sub") or payload.get("user_id") or payload.get("uid")
        if user:
            return str(user)
    except JWTError:
        pass
    return None


async def get_current_user_id(
    api_key: str | None = Depends(_api_key_header),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """
    Resolve current user from API key or JWT. Raises 401 if neither is valid.
    """
    user_id = get_user_id_from_api_key(api_key)
    if user_id:
        return user_id
    user_id = get_user_id_from_jwt(credentials)
    if user_id:
        return user_id
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid authentication (API key or Bearer token)",
    )
