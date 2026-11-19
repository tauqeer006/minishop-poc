from pymongo.errors import DuplicateKeyError

from app.observability.error_handlers import AppError
from app.observability.event_logger import audit
from app.observability.tracing import span, tdb
from app.utils.security import create_access_token, hash_password, verify_password
from app.utils.serialization import new_id, utcnow


def _user_view(user: dict) -> dict:
    return {k: user[k] for k in ("_id", "name", "email", "role", "created_at")}


async def register(name: str, email: str, password: str) -> dict:
    with span("register_user", "business"):
        user = {
            "_id": new_id("usr"),
            "name": name.strip(),
            "email": email.lower(),
            "password_hash": await hash_password(password),
            "role": "customer",  # self-registration can never create an admin
            "created_at": utcnow(),
        }
        try:
            await tdb().users.insert_one(user)
        except DuplicateKeyError:
            raise AppError(409, "EMAIL_ALREADY_REGISTERED", "An account with this email already exists.") from None
    await audit("USER_REGISTERED", "user", user["_id"], actor_id=user["_id"], after={"email": user["email"]})
    return {"user": _user_view(user), "access_token": create_access_token(user["_id"], user["role"]),
            "token_type": "bearer"}


async def login(email: str, password: str) -> dict:
    with span("login_user", "business"):
        user = await tdb().users.find_one({"email": email.lower()})
        ok = bool(user) and await verify_password(password, user["password_hash"])
        if not ok:  # same response for unknown email and wrong password
            raise AppError(401, "INVALID_CREDENTIALS", "Invalid email or password.",
                           event_type="AUTHENTICATION_FAILURE", context={"reason": "bad_credentials"})
    return {"user": _user_view(user), "access_token": create_access_token(user["_id"], user["role"]),
            "token_type": "bearer"}
