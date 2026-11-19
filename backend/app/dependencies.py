import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.observability.error_handlers import AppError
from app.observability.tracing import current, span, tdb
from app.utils.security import decode_access_token

bearer = HTTPBearer(auto_error=False)


def _auth_error(message: str = "Authentication required.") -> AppError:
    return AppError(401, "AUTH_REQUIRED", message, event_type="AUTHENTICATION_FAILURE",
                    headers={"WWW-Authenticate": "Bearer"})


async def _load_user(creds: HTTPAuthorizationCredentials) -> dict:
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise _auth_error("Invalid or expired token.") from None
    user = await tdb().users.find_one({"_id": payload.get("sub")}, projection={"password_hash": 0})
    if not user:
        raise _auth_error("Invalid or expired token.")
    ctx = current()
    if ctx:
        ctx.user_id = user["_id"]
    return user


async def get_optional_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict | None:
    if creds is None:
        return None
    with span("authentication", "auth"):
        return await _load_user(creds)


async def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    with span("authentication", "auth"):
        if creds is None:
            raise _auth_error()
        return await _load_user(creds)


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    with span("authorization", "authorization", required_role="admin"):
        if user.get("role") != "admin":
            raise AppError(
                403, "FORBIDDEN", "Administrator access required.",
                event_type="AUTHORIZATION_FAILURE",
                context={"required_role": "admin", "actual_role": user.get("role")},
            )
    return user
